from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import repository
from app.models import Base
from app.schemas import EventCreate, ReadingCreate


def _seeded_database_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "skills.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    readings = [
        {
            "city": "Ottawa",
            "timestamp": base,
            "temperature_2m": 3.0,
            "apparent_temperature": 1.0,
            "precipitation": 0.0,
            "wind_speed_10m": 12.0,
            "weather_code": 1,
            "weather_category": "cloudy",
        },
        {
            "city": "Ottawa",
            "timestamp": base + timedelta(hours=2),
            "temperature_2m": -2.0,
            "apparent_temperature": -7.0,
            "precipitation": 0.3,
            "wind_speed_10m": 22.0,
            "weather_code": 61,
            "weather_category": "rain",
        },
        {
            "city": "Toronto",
            "timestamp": base + timedelta(hours=2),
            "temperature_2m": 10.0,
            "apparent_temperature": 11.0,
            "precipitation": 0.0,
            "wind_speed_10m": 18.0,
            "weather_code": 1,
            "weather_category": "cloudy",
        },
        {
            "city": "Vancouver",
            "timestamp": base + timedelta(hours=2),
            "temperature_2m": 8.5,
            "apparent_temperature": 8.5,
            "precipitation": 0.0,
            "wind_speed_10m": 16.0,
            "weather_code": 1,
            "weather_category": "cloudy",
        },
    ]
    events = [
        {
            "city": "Toronto",
            "timestamp": base + timedelta(hours=1),
            "event_type": "temperature_swing",
            "severity": "moderate",
            "message": "Temperature rose quickly in Toronto",
            "reason": "hour-to-hour change exceeded the city threshold",
            "metric": "temperature_2m",
            "current_value": 8.0,
            "previous_value": 6.0,
            "threshold": 5.0,
            "reading_id": None,
        },
        {
            "city": "Toronto",
            "timestamp": base + timedelta(hours=2),
            "event_type": "wind_spike",
            "severity": "high",
            "message": "Wind increased sharply in Toronto",
            "reason": "wind became both strong and abruptly stronger",
            "metric": "wind_speed_10m",
            "current_value": 18.0,
            "previous_value": 11.0,
            "threshold": 35.0,
            "reading_id": None,
        },
    ]

    with session_local() as session:
        for payload in readings:
            repository.insert_reading_if_new(session, ReadingCreate(**payload))
        for payload in events:
            repository.insert_event_if_new(session, EventCreate(**payload))

    engine.dispose()
    return db_path


def test_analyze_weather_skill_runs_from_documented_entrypoint(tmp_path: Path) -> None:
    db_path = _seeded_database_path(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            ".cursor/skills/analyze_weather_data.py",
            "--database-url",
            f"sqlite:///{db_path}",
            "--question",
            "Which city has generated the most events?",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout.lower()
    assert "Toronto" in result.stdout


def test_replay_event_skill_runs_from_documented_entrypoint(tmp_path: Path) -> None:
    db_path = _seeded_database_path(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            ".cursor/skills/replay_event_detection.py",
            "--database-url",
            f"sqlite:///{db_path}",
            "--limit",
            "6",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout.lower()
    assert '"replay"' in result.stdout.lower()
