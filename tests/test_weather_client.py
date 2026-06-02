from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.cities import CITIES
from app.config import Settings
from app.weather_client import (
    WeatherClient,
    WeatherHTTPError,
    WeatherParseError,
    WeatherTimeoutError,
)


@pytest.mark.asyncio
async def test_weather_client_parses_open_meteo_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "current": {
                    "time": "2026-01-01T12:00",
                    "temperature_2m": 10.5,
                    "apparent_temperature": 7.5,
                    "precipitation": 0.2,
                    "wind_speed_10m": 34.0,
                    "weather_code": 63,
                },
                "utc_offset_seconds": -18000,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = WeatherClient(http_client, settings=Settings(enable_poller=False))
        result = await client.fetch_current_weather(CITIES["Toronto"])

    assert result["city"] == "Toronto"
    assert result["timestamp"] == datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)
    assert result["temperature_2m"] == 10.5
    assert result["weather_category"] == "rain"


@pytest.mark.asyncio
async def test_weather_client_malformed_response_raises_clear_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"unexpected": "payload"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = WeatherClient(http_client, settings=Settings(enable_poller=False))
        with pytest.raises(WeatherParseError, match="missing 'current' object"):
            await client.fetch_current_weather(CITIES["Toronto"])


@pytest.mark.asyncio
async def test_weather_client_requires_utc_offset_for_local_timestamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "current": {
                    "time": "2026-01-01T12:00",
                    "temperature_2m": 10.5,
                    "apparent_temperature": 7.5,
                    "precipitation": 0.2,
                    "wind_speed_10m": 34.0,
                    "weather_code": 63,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = WeatherClient(http_client, settings=Settings(enable_poller=False))
        with pytest.raises(
            WeatherParseError,
            match="missing 'utc_offset_seconds' for local timestamp",
        ):
            await client.fetch_current_weather(CITIES["Toronto"])


@pytest.mark.asyncio
async def test_weather_client_http_error_raises_clear_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=503, text="service unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = WeatherClient(http_client, settings=Settings(enable_poller=False))
        with pytest.raises(WeatherHTTPError, match="Open-Meteo HTTP 503"):
            await client.fetch_current_weather(CITIES["Toronto"])


@pytest.mark.asyncio
async def test_weather_client_timeout_raises_clear_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = WeatherClient(
            http_client,
            settings=Settings(enable_poller=False, request_timeout_seconds=2),
        )
        with pytest.raises(WeatherTimeoutError, match="timed out"):
            await client.fetch_current_weather(CITIES["Toronto"])
