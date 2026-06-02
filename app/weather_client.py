from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.cities import CityConfig
from app.config import Settings, get_settings
from app.weather_codes import categorize_weather_code

CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
)


class WeatherClientError(Exception):
    """Base error for weather client failures."""


class WeatherHTTPError(WeatherClientError):
    def __init__(self, city: str, status_code: int, detail: str) -> None:
        self.city = city
        self.status_code = status_code
        super().__init__(
            f"Open-Meteo HTTP {status_code} for {city}: {detail}",
        )


class WeatherTimeoutError(WeatherClientError):
    def __init__(self, city: str, timeout_seconds: float) -> None:
        self.city = city
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Open-Meteo request timed out after {timeout_seconds}s for {city}",
        )


class WeatherParseError(WeatherClientError):
    def __init__(self, city: str, detail: str) -> None:
        self.city = city
        super().__init__(f"Malformed Open-Meteo response for {city}: {detail}")


class WeatherClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def fetch_current_weather(self, city: CityConfig) -> dict[str, Any]:
        params = {
            "latitude": city.lat,
            "longitude": city.lon,
            "current": ",".join(CURRENT_FIELDS),
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        }

        try:
            response = await self._client.get(
                self._settings.open_meteo_base_url,
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise WeatherTimeoutError(
                city.name,
                float(self._settings.request_timeout_seconds),
            ) from exc
        except httpx.HTTPError as exc:
            raise WeatherClientError(
                f"Open-Meteo request failed for {city.name}: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise WeatherHTTPError(
                city.name,
                response.status_code,
                response.text[:200],
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherParseError(city.name, "response is not valid JSON") from exc

        return parse_current_response(city.name, payload)


def parse_current_response(city: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = payload.get("current")
    if not isinstance(current, dict):
        raise WeatherParseError(city, "missing 'current' object")

    time_value = current.get("time")
    if not isinstance(time_value, str):
        raise WeatherParseError(city, "missing or invalid 'current.time'")

    try:
        timestamp = datetime.fromisoformat(time_value)
    except ValueError as exc:
        raise WeatherParseError(city, f"invalid timestamp '{time_value}'") from exc

    if timestamp.tzinfo is None:
        utc_offset_seconds = payload.get("utc_offset_seconds")
        if not isinstance(utc_offset_seconds, int):
            raise WeatherParseError(
                city,
                "missing 'utc_offset_seconds' for local timestamp",
            )
        timestamp = timestamp.replace(
            tzinfo=timezone(timedelta(seconds=utc_offset_seconds)),
        )

    timestamp = timestamp.astimezone(timezone.utc)

    parsed: dict[str, Any] = {
        "city": city,
        "timestamp": timestamp,
    }

    for field in CURRENT_FIELDS:
        if field not in current or current[field] is None:
            raise WeatherParseError(city, f"missing 'current.{field}'")
        try:
            if field == "weather_code":
                parsed[field] = int(current[field])
            else:
                parsed[field] = float(current[field])
        except (TypeError, ValueError) as exc:
            raise WeatherParseError(
                city,
                f"invalid value for 'current.{field}'",
            ) from exc

    parsed["weather_category"] = categorize_weather_code(parsed["weather_code"])
    return parsed
