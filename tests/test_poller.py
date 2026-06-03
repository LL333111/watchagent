from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import repository
from app.config import Settings
from app.models import Base, Event
from app.poller import WeatherPoller
from app.weather_client import WeatherClientError


class DummyWeatherClient:
    def __init__(self, reading: dict[str, object]) -> None:
        self._reading = reading

    async def fetch_current_weather(self, _city: object) -> dict[str, object]:
        return self._reading


def _reading(city: str = "Toronto") -> dict[str, object]:
    return {
        "city": city,
        "timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "temperature_2m": 10.0,
        "apparent_temperature": 8.0,
        "precipitation": 0.0,
        "wind_speed_10m": 20.0,
        "weather_code": 1,
        "weather_category": "cloudy",
    }


@pytest.mark.asyncio
async def test_duplicate_reading_skips_event_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    poller = WeatherPoller(settings=Settings(enable_poller=False))
    reading_data = _reading("Toronto")

    fake_session = MagicMock()
    fake_reading = SimpleNamespace(id=1, timestamp=reading_data["timestamp"])

    monkeypatch.setattr("app.poller.SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        "app.poller.repository.insert_reading_if_new",
        lambda db, reading: (fake_reading, False),
    )
    detect_mock = MagicMock(return_value=[])
    insert_events_mock = MagicMock(return_value=[])
    monkeypatch.setattr("app.poller.detect_city_events", detect_mock)
    monkeypatch.setattr("app.poller.repository.insert_events_if_new", insert_events_mock)

    await poller._poll_city(DummyWeatherClient(reading_data), SimpleNamespace(name="Toronto"))

    detect_mock.assert_not_called()
    insert_events_mock.assert_not_called()


@pytest.mark.asyncio
async def test_one_city_failure_does_not_stop_other_cities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poller = WeatherPoller(settings=Settings(enable_poller=False))
    attempted: list[str] = []

    class FakeWeatherClient:
        def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
            self.client = client
            self.settings = settings

    async def fake_poll_city(self: WeatherPoller, weather_client: object, city: object) -> None:
        city_name = city.name
        attempted.append(city_name)
        if city_name == "Toronto":
            raise WeatherClientError("boom")

    monkeypatch.setattr("app.poller.WeatherClient", FakeWeatherClient)
    monkeypatch.setattr("app.poller.WeatherPoller._poll_city", fake_poll_city)

    async with httpx.AsyncClient() as client:
        await poller._poll_all_cities(client)

    assert attempted == ["Ottawa", "Toronto", "Vancouver"]


@pytest.mark.asyncio
async def test_poller_uses_insert_reading_if_new(monkeypatch: pytest.MonkeyPatch) -> None:
    poller = WeatherPoller(settings=Settings(enable_poller=False))
    reading_data = _reading("Toronto")

    fake_session = MagicMock()
    fake_reading = SimpleNamespace(id=9, timestamp=reading_data["timestamp"])

    insert_reading_mock = MagicMock(return_value=(fake_reading, True))
    monkeypatch.setattr("app.poller.SessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.poller.repository.insert_reading_if_new", insert_reading_mock)
    monkeypatch.setattr("app.poller.repository.get_previous_reading", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.poller.detect_city_events", lambda *args, **kwargs: [])

    await poller._poll_city(DummyWeatherClient(reading_data), SimpleNamespace(name="Toronto"))

    insert_reading_mock.assert_called_once()


@pytest.mark.asyncio
async def test_poller_uses_insert_events_if_new(monkeypatch: pytest.MonkeyPatch) -> None:
    poller = WeatherPoller(settings=Settings(enable_poller=False))
    reading_data = _reading("Toronto")

    fake_session = MagicMock()
    fake_reading = SimpleNamespace(id=11, timestamp=reading_data["timestamp"])
    event_dict = {
        "city": "Toronto",
        "timestamp": reading_data["timestamp"],
        "event_type": "wind_spike",
        "severity": "high",
        "message": "msg",
        "reason": "reason",
        "metric": "wind_speed_10m",
        "current_value": 40.0,
        "previous_value": 20.0,
        "threshold": 35.0,
    }

    monkeypatch.setattr("app.poller.SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        "app.poller.repository.insert_reading_if_new",
        lambda db, reading: (fake_reading, True),
    )
    monkeypatch.setattr("app.poller.repository.get_previous_reading", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.poller.detect_city_events", lambda *args, **kwargs: [event_dict])
    insert_events_mock = MagicMock(return_value=[(SimpleNamespace(id=1), True)])
    monkeypatch.setattr("app.poller.repository.insert_events_if_new", insert_events_mock)

    await poller._poll_city(DummyWeatherClient(reading_data), SimpleNamespace(name="Toronto"))

    insert_events_mock.assert_called_once()


@pytest.mark.asyncio
async def test_poll_once_deduplicates_same_city_timestamp_and_skips_repeat_detection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "poller-dedup.db"
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

    poller = WeatherPoller(settings=Settings(enable_poller=False))
    reading_data = _reading("Toronto")

    class FakeWeatherClient:
        def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
            self.client = client
            self.settings = settings

        async def fetch_current_weather(self, _city: object) -> dict[str, object]:
            return reading_data

    detect_mock = MagicMock(return_value=[])
    monkeypatch.setattr("app.poller.SessionLocal", testing_session_local)
    monkeypatch.setattr("app.poller.WeatherClient", FakeWeatherClient)
    monkeypatch.setattr("app.poller.detect_city_events", detect_mock)
    monkeypatch.setattr("app.poller.CITY_ORDER", ("Toronto",))

    try:
        await poller.poll_once()
        await poller.poll_once()

        with testing_session_local() as session:
            assert repository.count_readings(session) == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    # Event detection should only run for the first (inserted) reading.
    detect_mock.assert_called_once()


@pytest.mark.asyncio
async def test_poll_once_stores_regional_weather_advantage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "poller-regional.db"
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

    readings_by_city = {
        "Ottawa": {
            **_reading("Ottawa"),
            "temperature_2m": 18.0,
            "apparent_temperature": 18.0,
            "precipitation": 0.0,
            "wind_speed_10m": 8.0,
            "weather_category": "clear",
        },
        "Toronto": {
            **_reading("Toronto"),
            "temperature_2m": 12.0,
            "apparent_temperature": 12.0,
            "precipitation": 0.8,
            "wind_speed_10m": 18.0,
            "weather_category": "rain",
        },
        "Vancouver": {
            **_reading("Vancouver"),
            "temperature_2m": 4.0,
            "apparent_temperature": 4.0,
            "precipitation": 0.5,
            "wind_speed_10m": 36.0,
            "weather_category": "storm",
        },
    }

    class FakeWeatherClient:
        def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
            self.client = client
            self.settings = settings

        async def fetch_current_weather(self, city: object) -> dict[str, object]:
            return readings_by_city[city.name]

    monkeypatch.setattr("app.poller.SessionLocal", testing_session_local)
    monkeypatch.setattr("app.poller.WeatherClient", FakeWeatherClient)

    poller = WeatherPoller(settings=Settings(enable_poller=False))
    try:
        await poller.poll_once()

        with testing_session_local() as session:
            event_types = [event.event_type for event in session.scalars(select(Event)).all()]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    assert "regional_weather_advantage" in event_types
