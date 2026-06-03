#!/usr/bin/env python3
"""Audit WatchAgent API contract alignment across routes, schemas, tests, README."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_ENDPOINTS = ("/health", "/readings", "/events")
READING_FIELDS = {
    "id",
    "city",
    "timestamp",
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
    "weather_category",
    "created_at",
}
EVENT_FIELDS = {
    "id",
    "city",
    "timestamp",
    "event_type",
    "severity",
    "message",
    "reason",
    "metric",
    "current_value",
    "previous_value",
    "threshold",
    "reading_id",
    "created_at",
}
HEALTH_FIELDS = {"status", "readings_stored", "events_stored"}


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _field_presence(text: str, fields: set[str]) -> dict[str, bool]:
    return {field: field in text for field in sorted(fields)}


def main() -> None:
    routes = _read("app/routes.py")
    schemas = _read("app/schemas.py")
    tests = _read("tests/test_api.py")
    readme = _read("README.md")

    endpoint_evidence = {
        endpoint: {
            "routes": endpoint in routes,
            "tests": endpoint in tests,
            "readme": endpoint in readme,
        }
        for endpoint in EXPECTED_ENDPOINTS
    }
    field_evidence = {
        "health": {
            "schemas": _field_presence(schemas, HEALTH_FIELDS),
            "tests": _field_presence(tests, HEALTH_FIELDS),
            "readme": _field_presence(readme, HEALTH_FIELDS),
        },
        "readings": {
            "schemas": _field_presence(schemas, READING_FIELDS),
            "tests": _field_presence(tests, READING_FIELDS),
            "readme": _field_presence(readme, READING_FIELDS),
        },
        "events": {
            "schemas": _field_presence(schemas, EVENT_FIELDS),
            "tests": _field_presence(tests, EVENT_FIELDS),
            "readme": _field_presence(readme, EVENT_FIELDS),
        },
    }
    required_behavior = {
        "city_filter_documented": "city" in readme and "city" in routes,
        "limit_documented": "limit" in readme and "limit" in routes,
        "limit_default_50": "default=50" in routes
        and ("default 50" in readme or "default `50`" in readme),
        "utc_offset_tested": "+00:00" in tests,
        "newest_first_tested": (
            "most recent first" in readme.lower()
            or "most-recent-first" in readme.lower()
        )
        and (
            "most_recent_first" in tests
            or "sorted(reading_times, reverse=True)" in tests
        ),
    }

    missing_endpoints = [
        endpoint
        for endpoint, evidence in endpoint_evidence.items()
        if not all(evidence.values())
    ]
    missing_fields = [
        f"{shape}.{location}.{field}"
        for shape, locations in field_evidence.items()
        for location, fields in locations.items()
        for field, present in fields.items()
        if not present
    ]
    missing_behavior = [
        name for name, present in required_behavior.items() if not present
    ]

    output = {
        "ok": not (missing_endpoints or missing_fields or missing_behavior),
        "endpoint_evidence": endpoint_evidence,
        "field_evidence": field_evidence,
        "required_behavior": required_behavior,
        "missing_endpoints": missing_endpoints,
        "missing_fields": missing_fields,
        "missing_behavior": missing_behavior,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
