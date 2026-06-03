# WatchAgent

WatchAgent monitors live weather for Ottawa, Toronto, and Vancouver, stores only
new hourly readings, detects notable weather transitions, and exposes both
readings and events through a FastAPI API.

This project is designed around one question: "what should an operator actually
notice?" The goal is not to emit as many alerts as possible. The goal is to
surface changes that alter the operating picture while suppressing predictable
noise.

## System Overview

Core responsibilities:

- Poll Open-Meteo current weather for three fixed cities.
- Store each reading once per `city + timestamp`.
- Normalize timestamps to UTC before persistence so cross-city ordering and
  analysis remain valid.
- Detect notable events only when a newly inserted reading represents a real
  transition.
- Expose health, readings, and events through an HTTP API.

## Architecture

```text
Open-Meteo API
    |
    v
WeatherClient
    |
    v
WeatherPoller
    |
    +--> Repository --> SQLite (readings, events)
    |
    +--> Event Detection
    |
    v
FastAPI Routes
```

Component map:

- `app/weather_client.py`
  Fetches upstream data, validates payload shape, and converts local upstream
  timestamps into UTC.
- `app/poller.py`
  Runs the background polling loop, isolates per-city failures, and only runs
  event detection for fresh readings.
- `app/repository.py`
  Encapsulates count, query, and idempotent insert behavior.
- `app/event_detection.py`
  Holds pure transition-based event logic.
- `app/data_analysis.py`
  Provides question-driven analysis over stored readings and stored events.
- `app/routes.py`
  Serves `/health`, `/readings`, and `/events`.

## Technology Choices

- FastAPI
  A good fit for a small typed HTTP API with clean response models and low
  framework overhead.
- SQLAlchemy + SQLite
  SQLite keeps the stack simple for a single-node take-home, while SQLAlchemy
  keeps persistence logic structured and testable.
- httpx
  Async HTTP client with good timeout/error handling and easy mocking in tests.
- pytest
  Clear test ergonomics for repository, API, poller, skill, and event logic.
- Docker Compose
  Makes the whole service start from a clean clone with one command.
- GitHub Actions
  Validates the test suite and Docker build on pushes to `main`.

Operational notes:

- The container runs as a non-root application user.
- The image and compose service both expose a `/health`-based health check.
- SQLite data persists in the mounted `./data` directory across restarts.

## Setup and Run

```bash
git clone <repo>
cd watchagent
cp .env.example .env
docker compose up --build
```

After startup:

- API: [http://localhost:8000](http://localhost:8000)
- Database file: `./data/watchagent.db`
- Poller: enabled by default
- Container health: `healthy` once `/health` returns `"ok"`

## Environment Variables

- `DATABASE_URL`
  SQLAlchemy connection string. Default: `sqlite:///./data/watchagent.db`
- `POLL_INTERVAL_SECONDS`
  Polling cadence for the background worker.
- `OPEN_METEO_BASE_URL`
  Upstream endpoint. Default points at Open-Meteo.
- `REQUEST_TIMEOUT_SECONDS`
  Timeout for upstream weather requests.
- `LOG_LEVEL`
  Logging verbosity.
- `ENABLE_POLLER`
  Set to `false` for API-only runs or tests.

## API Reference

### GET /health

```bash
curl -s http://localhost:8000/health
```

Example response:

```json
{
  "status": "ok",
  "readings_stored": 42,
  "events_stored": 9
}
```

### GET /readings?city=Ottawa&limit=50

```bash
curl -s "http://localhost:8000/readings?city=Ottawa&limit=50"
```

Example response:

```json
{
  "readings": [
    {
      "id": 101,
      "city": "Ottawa",
      "timestamp": "2026-06-02T16:00:00+00:00",
      "temperature_2m": 19.4,
      "apparent_temperature": 18.8,
      "precipitation": 0.0,
      "wind_speed_10m": 14.0,
      "weather_code": 1,
      "weather_category": "cloudy",
      "created_at": "2026-06-02T16:00:02+00:00"
    }
  ]
}
```

### GET /events?city=Ottawa&limit=50

```bash
curl -s "http://localhost:8000/events?city=Ottawa&limit=50"
```

Example response:

```json
{
  "events": [
    {
      "id": 301,
      "city": "Ottawa",
      "timestamp": "2026-06-02T16:00:00+00:00",
      "event_type": "wind_spike",
      "severity": "high",
      "message": "Wind speed spiked to 41.0 km/h (+18.0 km/h) in Ottawa",
      "reason": "wind became both strong and abruptly stronger, which is more actionable than either condition alone",
      "metric": "wind_speed_10m",
      "current_value": 41.0,
      "previous_value": 23.0,
      "threshold": 35.0,
      "reading_id": 101,
      "created_at": "2026-06-02T16:00:03+00:00"
    }
  ]
}
```

## Event Detection Design

### Design Principles

- Transitions beat static thresholds.
  The system only stores a new reading once per upstream timestamp, and event
  logic is built around what changed between readings rather than reminding the
  operator that bad weather is still bad.
- First readings are not alerts.
  A single bootstrap reading lacks context. The system waits for transitions.
- City context matters.
  A 4C swing is more notable in Vancouver than in Ottawa, so temperature swing
  thresholds are city-specific.
- Every event should explain its monitoring value.
  `message` says what happened. `reason` says why the system judged it notable.

### Implemented Event Families

1. `temperature_swing`
   Fires when the absolute hour-to-hour temperature change meets or exceeds the city's
   swing threshold.

   Thresholds:
   - Ottawa: `6.0C`
   - Toronto: `5.0C`
   - Vancouver: `4.0C`

   Why this exists:
   Vancouver is more thermally stable than Ottawa, so a smaller swing is more
   informative there. The event is intentionally city-tuned rather than using
   one generic threshold everywhere.

2. `feels_like_stress`
   Fires when apparent temperature diverges enough from air temperature to push
   conditions into a cold-stress or heat-stress band.

   Trigger:
   - apparent temperature enters `<= 0C` or `>= 30C`
   - gap between apparent and actual temperature is at least `6.0C`
   - the same stress state was not already active in the previous reading

   Why this exists:
   A large apparent-temperature gap matters when it changes how conditions are
   experienced, not when it is merely numerically interesting.

3. `freeze_thaw_transition`
   Fires when air temperature clearly crosses freezing, using a `1.0C` margin to
   avoid noise right around zero.

   Trigger:
   - `>= 1.0C` to `<= -1.0C`, or
   - `<= -1.0C` to `>= 1.0C`

   Why this exists:
   Crossing freezing is operationally important because road, walkway, and
   surface conditions can change quickly even if the absolute temperature change
   is not huge.

4. `wind_spike`
   Fires when wind is both strong and abruptly stronger.

   Trigger:
   - current wind speed `>= 35 km/h`
   - increase from previous reading `>= 15 km/h`

   Why this exists:
   This avoids alerting on merely breezy conditions and also avoids repeatedly
   alerting on stable high wind.

5. `precipitation_started`
   Fires on a real dry-to-wet transition.

   Trigger:
   - previous precipitation effectively dry (`<= 0.05 mm`)
   - current precipitation is at least `0.2 mm`, or the current weather category
     has already shifted into `rain`, `snow`, or `storm` even if the measured
     accumulation is still below `0.2 mm`

   Why this exists:
   The operational change from dry to wet matters more than continued
   precipitation. Trace drizzle is intentionally suppressed.

6. `weather_regime_shift`
   Fires when the weather type changes into a materially different regime.

   Trigger examples:
   - clear/cloudy to fog/rain/snow/storm
   - rain to snow or snow to rain
   - anything into storm

   Why this exists:
   Operators care more about regime changes than churn between nearby WMO codes.

## Deduplication and Storage Rules

- `readings` are unique by `city + timestamp`
- `events` are unique by `city + timestamp + event_type`
- Duplicate readings do not re-run event detection
- Duplicate events are treated as safe idempotent outcomes, not errors

## Cursor Setup

The `.cursor/` folder is part of the solution, not decoration. Each artifact is
scoped to a concrete problem in this codebase.

### Rules

- `.cursor/rules/polling-and-storage.mdc`
  Protects storage invariants: UTC normalization, per-city failure isolation,
  dedup keys, and "only detect events for newly inserted readings."

- `.cursor/rules/event-detection.mdc`
  Forces event logic toward transitions, blocks bootstrap alerts, and requires
  operator-facing `reason` fields.

- `.cursor/rules/event-records.mdc`
  Standardizes event payload quality: severity meaning, message quality, and
  keeping `metric/current_value/previous_value/threshold` semantically honest.

- `.cursor/rules/testing.mdc`
  Keeps mocks, API ordering checks, trigger/non-trigger cases, and skill testing
  from being skipped.

### Agents

- `.cursor/agents/weather-event-reviewer.md`
  A reviewer agent that only audits signal quality, threshold defensibility,
  event payload clarity, and README/test alignment.

- `.cursor/agents/weather-data-analyst.md`
  A dataset-focused agent that uses the analysis and replay skills to answer
  questions about what the stored data is actually showing.

### Skills

- `.cursor/skills/analyze_weather_data.py`
  Question-driven data analysis. It answers concrete questions from stored
  readings and events rather than printing a generic dump. Run it from the
  repository root after the service has collected data, or pass `--database-url`
  to point at a specific SQLite file.

  Example commands:

  ```bash
  python .cursor/skills/analyze_weather_data.py --question "Which city is warmest right now?"
  python .cursor/skills/analyze_weather_data.py --question "Has Vancouver been getting windier?" --limit 12
  python .cursor/skills/analyze_weather_data.py --question "Which city has generated the most events?"
  ```

- `.cursor/skills/replay_event_detection.py`
  Replays event logic over recent stored readings so signal sensitivity and noise
  can be inspected against real history. Run it from the repository root after
  the service has collected data, or pass `--database-url` to point at a
  specific SQLite file.

  Example commands:

  ```bash
  python .cursor/skills/replay_event_detection.py --city Vancouver --limit 30
  python .cursor/skills/replay_event_detection.py --limit 60
  ```

Why this setup is project-specific:

- The rules are built around this repository's actual failure, dedup, and event
  semantics.
- The reviewer agent is specifically about weather signal quality, not generic
  code review.
- The analyst agent and question-driven skill exist because this challenge asks
  for defensible monitoring logic, which requires being able to interrogate the
  collected dataset directly.
- The replay skill makes quiet windows explainable: if no events fire in a
  recent slice, it returns a structured summary rather than implying that the
  service is broken.

Typical review workflow:

1. Let the service collect readings into SQLite.
2. Use `analyze_weather_data.py` to answer cross-city or single-city questions.
3. Use `replay_event_detection.py` to inspect whether recent history was quiet
   because conditions were stable or because the thresholds are too conservative.
4. Use the reviewer agent to compare event logic, tests, and README reasoning
   before changing thresholds or definitions.

## Testing

Run tests:

```bash
pytest
```

Or inside Docker:

```bash
docker build -t watchagent .
docker run --rm watchagent pytest
```

Test coverage includes:

- reading and event deduplication
- event trigger and non-trigger cases for every event family
- event boundary cases such as threshold-equality, heat-stress entry, and
  regime-shift transitions
- API response shape, exact stored fields, filtering, limits, and newest-first ordering
- poller behavior and duplicate short-circuiting
- weather client parsing, timeout handling, and UTC timestamp normalization
- analysis skill behavior for question-driven data interrogation
- documented skill entrypoint execution from the repository root

## CI

The GitHub Actions workflow in `.github/workflows/ci.yml` runs two jobs:

- `Test`
  Installs dependencies and runs `pytest`
- `Docker Build`
  Runs `docker build .`

This matches the challenge requirement that the latest `main` branch commit
should have both test and build checks passing.

## Repository Layout

```text
watchagent/
  app/
  tests/
  .cursor/
    agents/
    rules/
    skills/
  data/
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

## Tradeoffs and Future Improvements

- I kept the stack single-service for clean-clone simplicity. A production
  version would likely separate API and poller.
- Current event logic is intentionally heuristic and explainable. The next step
  would be learning seasonal baselines from accumulated history rather than using
  only fixed thresholds.
- Cross-city comparisons currently live in the analysis skill instead of the
  persisted event stream. That was a deliberate choice to keep the stored event
  model focused on per-city operational transitions while still supporting
  comparative reasoning during review.
- Quiet live windows are a real possibility because the event logic is tuned to
  prefer selective transition signals over constant reminders. When no recent
  events fire, the analysis and replay skills now report that explicitly so the
  output reads as "calm conditions" rather than "missing data."
