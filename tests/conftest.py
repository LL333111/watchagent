from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_db
from app.models import Base


@pytest.fixture
def db_session(tmp_path: Path) -> Generator[Session, None, None]:
    db_path = tmp_path / "watchagent-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    from app.main import app

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: type("Settings", (), {"enable_poller": False})(),
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def reading_payload() -> dict[str, object]:
    return {
        "city": "Toronto",
        "timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "temperature_2m": 10.0,
        "apparent_temperature": 8.0,
        "precipitation": 0.0,
        "wind_speed_10m": 20.0,
        "weather_code": 1,
        "weather_category": "cloudy",
    }


@pytest.fixture
def event_payload(reading_payload: dict[str, object]) -> dict[str, object]:
    return {
        "city": str(reading_payload["city"]),
        "timestamp": reading_payload["timestamp"],
        "event_type": "temperature_swing",
        "severity": "moderate",
        "message": "Temperature changed quickly",
        "reason": "test reason",
        "metric": "temperature_2m",
        "current_value": 16.0,
        "previous_value": 10.0,
        "threshold": 5.0,
        "reading_id": None,
    }
