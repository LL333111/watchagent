from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import repository
from app.data_analysis import analyze_weather_question
from app.models import Base
from app.schemas import EventCreate, ReadingCreate


def _seed_database(db_path: Path) -> str:
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
            "timestamp": base + timedelta(hours=1),
            "temperature_2m": 1.0,
            "apparent_temperature": -2.0,
            "precipitation": 0.0,
            "wind_speed_10m": 15.0,
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
            "timestamp": base,
            "temperature_2m": 6.0,
            "apparent_temperature": 5.0,
            "precipitation": 0.0,
            "wind_speed_10m": 11.0,
            "weather_code": 0,
            "weather_category": "clear",
        },
        {
            "city": "Toronto",
            "timestamp": base + timedelta(hours=1),
            "temperature_2m": 8.0,
            "apparent_temperature": 8.0,
            "precipitation": 0.0,
            "wind_speed_10m": 14.0,
            "weather_code": 1,
            "weather_category": "cloudy",
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
            "timestamp": base,
            "temperature_2m": 7.0,
            "apparent_temperature": 7.0,
            "precipitation": 0.2,
            "wind_speed_10m": 9.0,
            "weather_code": 63,
            "weather_category": "rain",
        },
        {
            "city": "Vancouver",
            "timestamp": base + timedelta(hours=1),
            "temperature_2m": 9.0,
            "apparent_temperature": 9.0,
            "precipitation": 0.0,
            "wind_speed_10m": 10.0,
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
        {
            "city": "Ottawa",
            "timestamp": base + timedelta(hours=2),
            "event_type": "freeze_thaw_transition",
            "severity": "high",
            "message": "Temperature crossed below freezing in Ottawa",
            "reason": "surface conditions can change quickly around freezing",
            "metric": "temperature_2m",
            "current_value": -2.0,
            "previous_value": 1.0,
            "threshold": 0.0,
            "reading_id": None,
        },
    ]

    with session_local() as session:
        for payload in readings:
            repository.insert_reading_if_new(session, ReadingCreate(**payload))
        for payload in events:
            repository.insert_event_if_new(session, EventCreate(**payload))

    engine.dispose()

    return f"sqlite:///{db_path}"


def test_analysis_skill_answers_latest_comparison_question(tmp_path: Path) -> None:
    database_url = _seed_database(tmp_path / "analysis.db")

    result = analyze_weather_question(
        database_url,
        "Which city is warmest right now?",
    )

    assert result["ok"] is True
    assert result["intent"] == "compare_latest"
    assert "Toronto" in result["answer"]
    assert result["evidence"]["ranking"][0]["city"] == "Toronto"


def test_analysis_skill_answers_city_trend_question(tmp_path: Path) -> None:
    database_url = _seed_database(tmp_path / "analysis.db")

    result = analyze_weather_question(
        database_url,
        "Has Ottawa been getting colder lately?",
        limit=3,
    )

    assert result["ok"] is True
    assert result["intent"] == "city_trend"
    assert result["city"] == "Ottawa"
    assert result["evidence"]["delta"] < 0


def test_analysis_skill_answers_event_pressure_question(tmp_path: Path) -> None:
    database_url = _seed_database(tmp_path / "analysis.db")

    result = analyze_weather_question(
        database_url,
        "Which city has generated the most events?",
    )

    assert result["ok"] is True
    assert result["intent"] == "event_pressure"
    assert "Toronto" in result["answer"]
    assert result["evidence"]["event_counts_by_city"]["Toronto"] == 2


def test_analysis_skill_understands_warmer_wording(tmp_path: Path) -> None:
    database_url = _seed_database(tmp_path / "analysis.db")

    result = analyze_weather_question(
        database_url,
        "Has Toronto been getting warmer lately?",
        limit=3,
    )

    assert result["ok"] is True
    assert result["intent"] == "city_trend"
    assert result["city"] == "Toronto"
    assert result["evidence"]["delta"] > 0
