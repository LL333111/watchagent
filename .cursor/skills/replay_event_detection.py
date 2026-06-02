#!/usr/bin/env python3
"""Replay WatchAgent event detection against recent stored readings.

Run from repository root:
    python .cursor/skills/replay_event_detection.py
    python .cursor/skills/replay_event_detection.py --city Vancouver --limit 30
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

from app.data_analysis import sqlite_path_from_database_url
from app.event_detection import detect_city_events


def load_recent_readings(
    conn: sqlite3.Connection,
    city: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    where = "WHERE city = ?" if city else ""
    params: tuple[Any, ...] = (city,) if city else ()
    rows = conn.execute(
        f"""
        SELECT city, timestamp, temperature_2m, apparent_temperature,
               precipitation, wind_speed_10m, weather_code, weather_category
        FROM readings
        {where}
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        params + (limit,),
    ).fetchall()
    # Replay in chronological order to preserve consecutive transitions.
    return [dict(row) for row in reversed(rows)]


def replay_events(readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Keep replay state per city so cross-city rows do not create false transitions.
    previous_by_city: dict[str, dict[str, Any]] = {}
    output: list[dict[str, Any]] = []
    for current in readings:
        city = str(current["city"])
        previous = previous_by_city.get(city)
        events = detect_city_events(city, current, previous)
        output.append(
            {
                "city": city,
                "timestamp": current["timestamp"],
                "events_fired": events,
                "event_types": [event["event_type"] for event in events],
                "event_count": len(events),
            }
        )
        previous_by_city[city] = current
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay WatchAgent event detection.")
    parser.add_argument(
        "--database-url",
        default="sqlite:///./data/watchagent.db",
        help="SQLAlchemy-style SQLite URL. Default: sqlite:///./data/watchagent.db",
    )
    parser.add_argument("--city", default=None, help="Optional city filter.")
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of recent readings used for replay. Default: 20.",
    )
    args = parser.parse_args()

    if args.limit < 2:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "--limit must be >= 2 for meaningful replay.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    try:
        db_path = sqlite_path_from_database_url(args.database_url)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return

    if not db_path.exists():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "Database file not found.",
                    "database_path": str(db_path),
                    "hint": "Run WatchAgent first or pass --database-url.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        readings = load_recent_readings(conn, args.city, args.limit)
        if not readings:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "database_path": str(db_path),
                        "city": args.city,
                        "limit": args.limit,
                        "message": "No readings found for replay.",
                        "readings_considered": 0,
                        "replay": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return

        replay = replay_events(readings)
        total_events = sum(item["event_count"] for item in replay)
        output = {
            "ok": True,
            "database_path": str(db_path),
            "city": args.city,
            "limit": args.limit,
            "readings_considered": len(readings),
            "total_events_fired": total_events,
            "replay": replay,
        }
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
