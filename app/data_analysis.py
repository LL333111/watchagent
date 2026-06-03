from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SUPPORTED_CITIES = ("Ottawa", "Toronto", "Vancouver")
DEFAULT_QUESTION = "Give me a concise overview of the latest weather across the monitored cities."


def sqlite_path_from_database_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite:/// database URLs are supported.")
    raw = database_url[len(prefix) :]
    if raw == ":memory:":
        raise ValueError("In-memory SQLite databases are not supported.")
    return Path(raw)


def analyze_weather_question(
    database_url: str,
    question: str | None = None,
    *,
    city: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if limit < 1:
        return {
            "ok": False,
            "error": "--limit must be >= 1",
        }

    try:
        db_path = sqlite_path_from_database_url(database_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if not db_path.exists():
        return {
            "ok": False,
            "error": "Database file not found.",
            "database_path": str(db_path),
            "hint": "Run the service first or pass --database-url.",
        }

    normalized_question = (question or DEFAULT_QUESTION).strip()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return _analyze_with_connection(
            conn,
            normalized_question,
            city=city,
            limit=limit,
            database_path=str(db_path),
        )
    finally:
        conn.close()


def _analyze_with_connection(
    conn: sqlite3.Connection,
    question: str,
    *,
    city: str | None,
    limit: int,
    database_path: str,
) -> dict[str, Any]:
    inferred_city = city or _extract_city(question)
    intent = _classify_question(question, inferred_city)

    if intent == "compare_latest":
        return _answer_compare_latest(
            conn,
            question,
            limit=limit,
            database_path=database_path,
        )
    if intent == "city_trend":
        return _answer_city_trend(
            conn,
            question,
            city=inferred_city,
            limit=limit,
            database_path=database_path,
        )
    if intent == "event_pressure":
        return _answer_event_pressure(
            conn,
            question,
            database_path=database_path,
        )
    if intent == "city_summary":
        return _answer_city_summary(
            conn,
            question,
            city=inferred_city,
            limit=limit,
            database_path=database_path,
        )
    return _answer_network_summary(
        conn,
        question,
        limit=limit,
        database_path=database_path,
    )


def _classify_question(question: str, city: str | None) -> str:
    normalized = question.lower()

    if any(
        token in normalized
        for token in (
            "warmest",
            "coldest",
            "hottest",
            "coolest",
            "windiest",
            "wettest",
            "highest precipitation",
            "lowest temperature",
        )
    ):
        return "compare_latest"

    if any(token in normalized for token in ("most events", "noisiest", "quietest")):
        return "event_pressure"

    if city is not None and any(
        token in normalized
        for token in (
            "trend",
            "warming",
            "cooling",
            "warmer",
            "colder",
            "cooler",
            "getting hotter",
            "getting colder",
            "windier",
            "precipitation",
            "raining more",
            "snowing more",
        )
    ):
        return "city_trend"

    if city is not None:
        return "city_summary"

    return "network_summary"


def _extract_city(question: str) -> str | None:
    normalized = question.lower()
    for city in SUPPORTED_CITIES:
        if city.lower() in normalized:
            return city
    return None


def _metric_from_question(question: str) -> tuple[str, str, bool]:
    normalized = question.lower()
    if any(token in normalized for token in ("wind", "windiest", "windier")):
        return "wind_speed_10m", "wind speed", True
    if any(
        token in normalized
        for token in ("rain", "snow", "precipitation", "wettest")
    ):
        return "precipitation", "precipitation", True
    if any(token in normalized for token in ("feels like", "apparent")):
        return "apparent_temperature", "apparent temperature", True
    if any(token in normalized for token in ("coldest", "coolest", "lowest temperature")):
        return "temperature_2m", "temperature", False
    return "temperature_2m", "temperature", True


def _latest_readings_by_city(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT city, timestamp, temperature_2m, apparent_temperature,
               precipitation, wind_speed_10m, weather_code, weather_category,
               created_at
        FROM readings
        ORDER BY city ASC, timestamp DESC
        """
    ).fetchall()
    latest_by_city: dict[str, dict[str, Any]] = {}
    for row in rows:
        city = str(row["city"])
        if city not in latest_by_city:
            latest_by_city[city] = dict(row)
    return latest_by_city


def _recent_readings(
    conn: sqlite3.Connection,
    *,
    city: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT city, timestamp, temperature_2m, apparent_temperature,
               precipitation, wind_speed_10m, weather_code, weather_category
        FROM readings
        WHERE city = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (city, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _event_counts_by_city(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT city, COUNT(*) AS count
        FROM events
        GROUP BY city
        ORDER BY city ASC
        """
    ).fetchall()
    return {str(row["city"]): int(row["count"]) for row in rows}


def _reading_counts_by_city(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT city, COUNT(*) AS count
        FROM readings
        GROUP BY city
        ORDER BY city ASC
        """
    ).fetchall()
    return {str(row["city"]): int(row["count"]) for row in rows}


def _event_type_counts(
    conn: sqlite3.Connection,
    *,
    city: str,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM events
        WHERE city = ?
        GROUP BY event_type
        ORDER BY count DESC, event_type ASC
        """,
        (city,),
    ).fetchall()
    return {str(row["event_type"]): int(row["count"]) for row in rows}


def _latest_event(
    conn: sqlite3.Connection,
    *,
    city: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT city, timestamp, event_type, severity, message, reason
        FROM events
        WHERE city = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (city,),
    ).fetchone()
    return dict(row) if row is not None else None


def _base_response(
    *,
    database_path: str,
    question: str,
    intent: str,
    city: str | None,
    limit: int,
    answer: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "database_path": database_path,
        "question": question,
        "intent": intent,
        "city": city,
        "limit": limit,
        "answer": answer,
        "evidence": evidence,
    }


def _answer_compare_latest(
    conn: sqlite3.Connection,
    question: str,
    *,
    limit: int,
    database_path: str,
) -> dict[str, Any]:
    latest_by_city = _latest_readings_by_city(conn)
    if not latest_by_city:
        return _empty_dataset_response(
            database_path=database_path,
            question=question,
            intent="compare_latest",
            city=None,
            limit=limit,
        )

    metric_key, metric_label, prefer_max = _metric_from_question(question)
    ranked = sorted(
        latest_by_city.values(),
        key=lambda row: float(row[metric_key]),
        reverse=prefer_max,
    )
    winner = ranked[0]
    answer = (
        f"{winner['city']} currently leads on {metric_label} at "
        f"{float(winner[metric_key]):.1f}."
    )
    return _base_response(
        database_path=database_path,
        question=question,
        intent="compare_latest",
        city=None,
        limit=limit,
        answer=answer,
        evidence={
            "metric": metric_key,
            "ranking": [
                {
                    "city": row["city"],
                    "value": float(row[metric_key]),
                    "timestamp": row["timestamp"],
                }
                for row in ranked
            ],
        },
    )


def _answer_city_trend(
    conn: sqlite3.Connection,
    question: str,
    *,
    city: str | None,
    limit: int,
    database_path: str,
) -> dict[str, Any]:
    if city is None:
        return _unsupported_response(
            database_path=database_path,
            question=question,
            intent="city_trend",
            city=None,
            limit=limit,
            detail="Trend questions must mention a city or pass --city.",
        )

    readings = _recent_readings(conn, city=city, limit=limit)
    if not readings:
        return _empty_dataset_response(
            database_path=database_path,
            question=question,
            intent="city_trend",
            city=city,
            limit=limit,
        )

    metric_key, metric_label, _ = _metric_from_question(question)
    newest = readings[0]
    oldest = readings[-1]
    delta = float(newest[metric_key]) - float(oldest[metric_key])
    direction = "up" if delta > 0.5 else "down" if delta < -0.5 else "flat"

    if direction == "up":
        answer = (
            f"{city}'s {metric_label} trend is up over the last {len(readings)} "
            f"stored readings ({float(oldest[metric_key]):.1f} -> "
            f"{float(newest[metric_key]):.1f})."
        )
    elif direction == "down":
        answer = (
            f"{city}'s {metric_label} trend is down over the last {len(readings)} "
            f"stored readings ({float(oldest[metric_key]):.1f} -> "
            f"{float(newest[metric_key]):.1f})."
        )
    else:
        answer = (
            f"{city}'s {metric_label} has been broadly flat over the last "
            f"{len(readings)} stored readings."
        )

    return _base_response(
        database_path=database_path,
        question=question,
        intent="city_trend",
        city=city,
        limit=limit,
        answer=answer,
        evidence={
            "metric": metric_key,
            "first_timestamp": oldest["timestamp"],
            "latest_timestamp": newest["timestamp"],
            "first_value": float(oldest[metric_key]),
            "latest_value": float(newest[metric_key]),
            "delta": round(delta, 2),
            "samples_considered": len(readings),
        },
    )


def _answer_event_pressure(
    conn: sqlite3.Connection,
    question: str,
    *,
    database_path: str,
) -> dict[str, Any]:
    counts = _event_counts_by_city(conn)
    if not counts:
        reading_counts = _reading_counts_by_city(conn)
        if not reading_counts:
            return _empty_dataset_response(
                database_path=database_path,
                question=question,
                intent="event_pressure",
                city=None,
                limit=50,
            )
        return _base_response(
            database_path=database_path,
            question=question,
            intent="event_pressure",
            city=None,
            limit=50,
            answer=(
                "Stored readings exist, but no notable events have been recorded yet. "
                "That usually means the recent window stayed inside the current "
                "signal thresholds."
            ),
            evidence={
                "event_counts_by_city": {},
                "reading_counts_by_city": reading_counts,
                "latest_by_city": _latest_readings_by_city(conn),
            },
        )

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    leader, leader_count = ranked[0]
    dominant_types = _event_type_counts(conn, city=leader)
    answer = (
        f"{leader} has generated the most notable events so far "
        f"({leader_count} total)."
    )
    return _base_response(
        database_path=database_path,
        question=question,
        intent="event_pressure",
        city=None,
        limit=50,
        answer=answer,
        evidence={
            "event_counts_by_city": counts,
            "leader_event_type_breakdown": dominant_types,
        },
    )


def _answer_city_summary(
    conn: sqlite3.Connection,
    question: str,
    *,
    city: str | None,
    limit: int,
    database_path: str,
) -> dict[str, Any]:
    if city is None:
        return _unsupported_response(
            database_path=database_path,
            question=question,
            intent="city_summary",
            city=None,
            limit=limit,
            detail="City summaries must mention a city or pass --city.",
        )

    readings = _recent_readings(conn, city=city, limit=limit)
    if not readings:
        return _empty_dataset_response(
            database_path=database_path,
            question=question,
            intent="city_summary",
            city=city,
            limit=limit,
        )

    latest = readings[0]
    latest_event = _latest_event(conn, city=city)
    event_type_counts = _event_type_counts(conn, city=city)
    answer = (
        f"{city} is currently {float(latest['temperature_2m']):.1f}C, feels like "
        f"{float(latest['apparent_temperature']):.1f}C, with "
        f"{float(latest['wind_speed_10m']):.1f} km/h wind and "
        f"{float(latest['precipitation']):.1f} mm precipitation."
    )
    return _base_response(
        database_path=database_path,
        question=question,
        intent="city_summary",
        city=city,
        limit=limit,
        answer=answer,
        evidence={
            "latest_reading": latest,
            "latest_event": latest_event,
            "event_type_counts": event_type_counts,
        },
    )


def _answer_network_summary(
    conn: sqlite3.Connection,
    question: str,
    *,
    limit: int,
    database_path: str,
) -> dict[str, Any]:
    latest_by_city = _latest_readings_by_city(conn)
    if not latest_by_city:
        return _empty_dataset_response(
            database_path=database_path,
            question=question,
            intent="network_summary",
            city=None,
            limit=limit,
        )

    hottest = max(
        latest_by_city.values(),
        key=lambda row: float(row["temperature_2m"]),
    )
    windiest = max(
        latest_by_city.values(),
        key=lambda row: float(row["wind_speed_10m"]),
    )
    answer = (
        f"Latest network snapshot: hottest city is {hottest['city']} at "
        f"{float(hottest['temperature_2m']):.1f}C and windiest city is "
        f"{windiest['city']} at {float(windiest['wind_speed_10m']):.1f} km/h."
    )
    return _base_response(
        database_path=database_path,
        question=question,
        intent="network_summary",
        city=None,
        limit=limit,
        answer=answer,
        evidence={
            "latest_by_city": latest_by_city,
            "event_counts_by_city": _event_counts_by_city(conn),
        },
    )


def _empty_dataset_response(
    *,
    database_path: str,
    question: str,
    intent: str,
    city: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "ok": True,
        "database_path": database_path,
        "question": question,
        "intent": intent,
        "city": city,
        "limit": limit,
        "answer": "No stored data is available for the requested scope yet.",
        "evidence": {},
    }


def _unsupported_response(
    *,
    database_path: str,
    question: str,
    intent: str,
    city: str | None,
    limit: int,
    detail: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "database_path": database_path,
        "question": question,
        "intent": intent,
        "city": city,
        "limit": limit,
        "error": detail,
        "supported_examples": [
            "Which city is warmest right now?",
            "Has Vancouver been getting windier?",
            "Give me a summary for Ottawa.",
            "Which city has generated the most events?",
        ],
    }
