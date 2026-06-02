import asyncio
import logging
from typing import Any

import httpx

from app.cities import CITIES, CityConfig
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.event_detection import detect_city_events
from app.models import Reading
from app import repository
from app.schemas import EventCreate, ReadingCreate
from app.weather_client import WeatherClient, WeatherClientError

logger = logging.getLogger(__name__)

CITY_ORDER = ("Ottawa", "Toronto", "Vancouver")


class WeatherPoller:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run_forever(self) -> None:
        logger.info(
            "Weather poller started (interval=%ss)",
            self._settings.poll_interval_seconds,
        )
        try:
            if self._owns_client:
                async with httpx.AsyncClient() as client:
                    await self._run_loop(client)
            else:
                await self._run_loop(self._http_client)
        finally:
            logger.info("Weather poller stopped")

    async def _run_loop(self, client: httpx.AsyncClient) -> None:
        while not self._stop_event.is_set():
            await self.poll_once(client)
            if self._stop_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._settings.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def poll_once(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if client is not None:
            await self._poll_all_cities(client)
            return

        if self._http_client is not None:
            await self._poll_all_cities(self._http_client)
            return

        async with httpx.AsyncClient() as owned_client:
            await self._poll_all_cities(owned_client)

    async def _poll_all_cities(self, client: httpx.AsyncClient) -> None:
        weather_client = WeatherClient(client, self._settings)
        for city_name in CITY_ORDER:
            city = CITIES.get(city_name)
            if city is None:
                continue
            try:
                await self._poll_city(weather_client, city)
            except WeatherClientError as exc:
                logger.warning("Weather fetch failed for %s: %s", city_name, exc)
            except Exception:
                logger.exception("Unexpected error polling %s", city_name)

    async def _poll_city(
        self,
        weather_client: WeatherClient,
        city: CityConfig,
    ) -> None:
        reading_data = await weather_client.fetch_current_weather(city)
        db = SessionLocal()
        try:
            reading_create = ReadingCreate(**reading_data)
            reading, inserted = repository.insert_reading_if_new(db, reading_create)
            if not inserted:
                logger.debug("Duplicate reading skipped for %s", city.name)
                return

            logger.info("Stored new reading for %s at %s", city.name, reading.timestamp)
            previous = repository.get_previous_reading(
                db,
                city.name,
                reading.timestamp,
            )
            previous_dict = _reading_to_dict(previous) if previous else None
            event_dicts = detect_city_events(
                city.name,
                reading_data,
                previous_dict,
            )
            if not event_dicts:
                return

            event_creates = [
                EventCreate(**{**event_dict, "reading_id": reading.id})
                for event_dict in event_dicts
            ]
            results = repository.insert_events_if_new(db, event_creates)
            new_count = sum(1 for _, was_inserted in results if was_inserted)
            if new_count:
                logger.info(
                    "Stored %s new event(s) for %s",
                    new_count,
                    city.name,
                )
        finally:
            db.close()


def _reading_to_dict(reading: Reading) -> dict[str, Any]:
    return {
        "city": reading.city,
        "timestamp": reading.timestamp,
        "temperature_2m": reading.temperature_2m,
        "apparent_temperature": reading.apparent_temperature,
        "precipitation": reading.precipitation,
        "wind_speed_10m": reading.wind_speed_10m,
        "weather_code": reading.weather_code,
        "weather_category": reading.weather_category,
    }
