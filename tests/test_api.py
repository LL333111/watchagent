from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import repository
from app.schemas import EventCreate, ReadingCreate


def _seed_readings(db_session: Session) -> None:
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    entries = [
        {
            "city": "Toronto",
            "timestamp": base + timedelta(minutes=0),
            "temperature_2m": 5.0,
            "apparent_temperature": 3.0,
            "precipitation": 0.0,
            "wind_speed_10m": 10.0,
            "weather_code": 0,
            "weather_category": "clear",
        },
        {
            "city": "Vancouver",
            "timestamp": base + timedelta(minutes=30),
            "temperature_2m": 8.0,
            "apparent_temperature": 7.0,
            "precipitation": 0.1,
            "wind_speed_10m": 15.0,
            "weather_code": 63,
            "weather_category": "rain",
        },
        {
            "city": "Toronto",
            "timestamp": base + timedelta(minutes=60),
            "temperature_2m": 9.0,
            "apparent_temperature": 9.0,
            "precipitation": 0.0,
            "wind_speed_10m": 12.0,
            "weather_code": 1,
            "weather_category": "cloudy",
        },
    ]
    for entry in entries:
        repository.insert_reading_if_new(db_session, ReadingCreate(**entry))


def _seed_events(db_session: Session) -> None:
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    entries = [
        {
            "city": "Toronto",
            "timestamp": base + timedelta(minutes=0),
            "event_type": "temperature_swing",
            "severity": "moderate",
            "message": "t1",
            "reason": "r1",
            "metric": "temperature_2m",
            "current_value": 10.0,
            "previous_value": 4.0,
            "threshold": 5.0,
            "reading_id": None,
        },
        {
            "city": "Vancouver",
            "timestamp": base + timedelta(minutes=30),
            "event_type": "precipitation_started",
            "severity": "moderate",
            "message": "t2",
            "reason": "r2",
            "metric": "precipitation",
            "current_value": 0.2,
            "previous_value": 0.0,
            "threshold": 0.0,
            "reading_id": None,
        },
        {
            "city": "Toronto",
            "timestamp": base + timedelta(minutes=60),
            "event_type": "wind_spike",
            "severity": "high",
            "message": "t3",
            "reason": "r3",
            "metric": "wind_speed_10m",
            "current_value": 40.0,
            "previous_value": 20.0,
            "threshold": 35.0,
            "reading_id": None,
        },
    ]
    for entry in entries:
        repository.insert_event_if_new(db_session, EventCreate(**entry))


def test_health_endpoint_returns_status_and_counts(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_readings(db_session)
    _seed_events(db_session)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["readings_stored"] == 3
    assert payload["events_stored"] == 3


def test_readings_endpoint_returns_expected_shape(client: TestClient, db_session: Session) -> None:
    _seed_readings(db_session)

    response = client.get("/readings")

    assert response.status_code == 200
    payload = response.json()
    assert "readings" in payload
    assert isinstance(payload["readings"], list)
    assert len(payload["readings"]) == 3


def test_events_endpoint_returns_expected_shape(client: TestClient, db_session: Session) -> None:
    _seed_events(db_session)

    response = client.get("/events")

    assert response.status_code == 200
    payload = response.json()
    assert "events" in payload
    assert isinstance(payload["events"], list)
    assert len(payload["events"]) == 3


def test_city_filter_works_for_readings_and_events(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_readings(db_session)
    _seed_events(db_session)

    readings_response = client.get("/readings", params={"city": "Vancouver"})
    events_response = client.get("/events", params={"city": "Vancouver"})

    assert readings_response.status_code == 200
    assert events_response.status_code == 200
    assert all(item["city"] == "Vancouver" for item in readings_response.json()["readings"])
    assert all(item["city"] == "Vancouver" for item in events_response.json()["events"])


def test_limit_works_for_readings_and_events(client: TestClient, db_session: Session) -> None:
    _seed_readings(db_session)
    _seed_events(db_session)

    readings_response = client.get("/readings", params={"limit": 2})
    events_response = client.get("/events", params={"limit": 2})

    assert readings_response.status_code == 200
    assert events_response.status_code == 200
    assert len(readings_response.json()["readings"]) == 2
    assert len(events_response.json()["events"]) == 2


def test_results_are_most_recent_first(client: TestClient, db_session: Session) -> None:
    _seed_readings(db_session)
    _seed_events(db_session)

    readings_response = client.get("/readings")
    events_response = client.get("/events")

    reading_times = [item["timestamp"] for item in readings_response.json()["readings"]]
    event_times = [item["timestamp"] for item in events_response.json()["events"]]

    assert reading_times == sorted(reading_times, reverse=True)
    assert event_times == sorted(event_times, reverse=True)
