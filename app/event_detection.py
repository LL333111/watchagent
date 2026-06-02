from datetime import datetime
from typing import Any

from app.cities import CITIES

CLEAR_CLOUDY = frozenset({"clear", "cloudy"})
IMPACTFUL_CATEGORIES = frozenset({"fog", "rain", "snow", "storm"})
PRECIPITATION_CATEGORIES = frozenset({"rain", "snow", "storm"})

FEELS_LIKE_GAP_THRESHOLD = 6.0
FREEZE_MARGIN = 1.0
HEAT_STRESS_BOUNDARY = 30.0
COLD_STRESS_BOUNDARY = 0.0
WIND_SPIKE_MIN_SPEED = 35.0
WIND_SPIKE_MIN_INCREASE = 15.0
MIN_NOTABLE_PRECIPITATION = 0.2


def detect_city_events(
    city: str,
    current_reading: dict[str, Any],
    previous_reading: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    city_config = CITIES.get(city)
    if city_config is None or previous_reading is None:
        return []

    timestamp = current_reading["timestamp"]
    events: list[dict[str, Any]] = []

    events.extend(
        _detect_temperature_swing(
            city,
            timestamp,
            current_reading,
            previous_reading,
            city_config.temperature_swing_threshold,
        ),
    )
    events.extend(
        _detect_feels_like_stress(
            city,
            timestamp,
            current_reading,
            previous_reading,
        ),
    )
    events.extend(
        _detect_freeze_thaw_transition(
            city,
            timestamp,
            current_reading,
            previous_reading,
        ),
    )
    events.extend(
        _detect_wind_spike(city, timestamp, current_reading, previous_reading),
    )
    events.extend(
        _detect_precipitation_started(
            city,
            timestamp,
            current_reading,
            previous_reading,
        ),
    )
    events.extend(
        _detect_weather_category_transition(
            city,
            timestamp,
            current_reading,
            previous_reading,
        ),
    )
    return events


def _base_event(
    city: str,
    timestamp: datetime,
    event_type: str,
    severity: str,
    message: str,
    reason: str,
    metric: str,
    current_value: float | None,
    previous_value: float | None,
    threshold: float | None,
) -> dict[str, Any]:
    return {
        "city": city,
        "timestamp": timestamp,
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "reason": reason,
        "metric": metric,
        "current_value": current_value,
        "previous_value": previous_value,
        "threshold": threshold,
    }


def _detect_temperature_swing(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
    threshold: float,
) -> list[dict[str, Any]]:
    current_temp = float(current["temperature_2m"])
    previous_temp = float(previous["temperature_2m"])
    swing = abs(current_temp - previous_temp)

    if swing < threshold:
        return []

    direction = "rose" if current_temp > previous_temp else "fell"
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="temperature_swing",
            severity="moderate" if swing < threshold + 3.0 else "high",
            message=(
                f"Temperature {direction} {swing:.1f}C since the previous reading "
                f"in {city}"
            ),
            reason=(
                "hour-to-hour temperature movement exceeded the city's noise "
                "tolerance threshold"
            ),
            metric="temperature_2m",
            current_value=current_temp,
            previous_value=previous_temp,
            threshold=threshold,
        ),
    ]


def _stress_band(apparent_temperature: float) -> str:
    if apparent_temperature <= COLD_STRESS_BOUNDARY:
        return "cold"
    if apparent_temperature >= HEAT_STRESS_BOUNDARY:
        return "heat"
    return "neutral"


def _detect_feels_like_stress(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_temp = float(current["temperature_2m"])
    previous_temp = float(previous["temperature_2m"])
    current_apparent = float(current["apparent_temperature"])
    previous_apparent = float(previous["apparent_temperature"])
    current_gap = abs(current_apparent - current_temp)
    previous_gap = abs(previous_apparent - previous_temp)
    current_band = _stress_band(current_apparent)
    previous_band = _stress_band(previous_apparent)

    if current_band == "neutral" or current_gap < FEELS_LIKE_GAP_THRESHOLD:
        return []

    if current_band == previous_band and previous_gap >= FEELS_LIKE_GAP_THRESHOLD:
        return []

    if current_band == "cold":
        severity = "high" if current_apparent <= -10.0 else "moderate"
        message = (
            f"Perceived cold stress developed in {city}: feels like "
            f"{current_apparent:.1f}C while the air temperature is "
            f"{current_temp:.1f}C"
        )
        reason = (
            f"perceived conditions dropped into the cold-stress band with a "
            f"{current_gap:.1f}C gap from the measured air temperature"
        )
        threshold = COLD_STRESS_BOUNDARY
    else:
        severity = "high" if current_apparent >= 35.0 else "moderate"
        message = (
            f"Perceived heat stress developed in {city}: feels like "
            f"{current_apparent:.1f}C while the air temperature is "
            f"{current_temp:.1f}C"
        )
        reason = (
            f"perceived conditions entered the heat-stress band with a "
            f"{current_gap:.1f}C gap from the measured air temperature"
        )
        threshold = HEAT_STRESS_BOUNDARY

    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="feels_like_stress",
            severity=severity,
            message=message,
            reason=reason,
            metric="apparent_temperature",
            current_value=current_apparent,
            previous_value=previous_apparent,
            threshold=threshold,
        ),
    ]


def _detect_freeze_thaw_transition(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_temp = float(current["temperature_2m"])
    previous_temp = float(previous["temperature_2m"])
    current_precip = float(current["precipitation"])
    current_category = str(current["weather_category"])

    if previous_temp >= FREEZE_MARGIN and current_temp <= -FREEZE_MARGIN:
        direction = "below"
    elif previous_temp <= -FREEZE_MARGIN and current_temp >= FREEZE_MARGIN:
        direction = "above"
    else:
        return []

    severity = (
        "high"
        if current_precip > 0 or current_category in PRECIPITATION_CATEGORIES
        else "moderate"
    )
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="freeze_thaw_transition",
            severity=severity,
            message=(
                f"Temperature crossed {direction} freezing in {city} "
                f"({previous_temp:.1f}C -> {current_temp:.1f}C)"
            ),
            reason=(
                "surface conditions can change quickly when air temperature "
                "moves across freezing"
            ),
            metric="temperature_2m",
            current_value=current_temp,
            previous_value=previous_temp,
            threshold=0.0,
        ),
    ]


def _detect_wind_spike(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_wind = float(current["wind_speed_10m"])
    previous_wind = float(previous["wind_speed_10m"])
    increase = current_wind - previous_wind

    if current_wind < WIND_SPIKE_MIN_SPEED or increase < WIND_SPIKE_MIN_INCREASE:
        return []

    severity = "high" if current_wind < 50.0 else "critical"
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="wind_spike",
            severity=severity,
            message=(
                f"Wind speed spiked to {current_wind:.1f} km/h "
                f"(+{increase:.1f} km/h) in {city}"
            ),
            reason=(
                "wind became both strong and abruptly stronger, which is more "
                "actionable than either condition alone"
            ),
            metric="wind_speed_10m",
            current_value=current_wind,
            previous_value=previous_wind,
            threshold=WIND_SPIKE_MIN_SPEED,
        ),
    ]


def _detect_precipitation_started(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_precip = float(current["precipitation"])
    previous_precip = float(previous["precipitation"])
    current_category = str(current["weather_category"])

    if previous_precip > 0.05:
        return []
    if current_precip < MIN_NOTABLE_PRECIPITATION and current_category not in PRECIPITATION_CATEGORIES:
        return []

    severity = (
        "high"
        if current_precip >= 2.0 or current_category in {"snow", "storm"}
        else "moderate"
    )
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="precipitation_started",
            severity=severity,
            message=(
                f"Dry conditions ended in {city} with {current_category} starting "
                f"at {current_precip:.1f} mm"
            ),
            reason=(
                "a dry-to-wet transition changes travel and outdoor conditions "
                "more than continued precipitation does"
            ),
            metric="precipitation",
            current_value=current_precip,
            previous_value=previous_precip,
            threshold=MIN_NOTABLE_PRECIPITATION,
        ),
    ]


def _is_notable_category_transition(
    previous_category: str,
    current_category: str,
) -> bool:
    if previous_category == current_category:
        return False

    if current_category == "storm" and previous_category != "storm":
        return True

    if previous_category in CLEAR_CLOUDY and current_category in IMPACTFUL_CATEGORIES:
        return True

    rain_snow_pair = {"rain", "snow"}
    return (
        previous_category in rain_snow_pair and current_category in rain_snow_pair
    )


def _detect_weather_category_transition(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    previous_category = str(previous["weather_category"])
    current_category = str(current["weather_category"])

    if not _is_notable_category_transition(previous_category, current_category):
        return []

    severity = (
        "high"
        if current_category == "storm" or {previous_category, current_category} == {"rain", "snow"}
        else "moderate"
    )
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="weather_regime_shift",
            severity=severity,
            message=(
                f"Weather regime shifted from {previous_category} to "
                f"{current_category} in {city}"
            ),
            reason=(
                "the new weather regime changes operating conditions more than "
                "minor code churn within the same regime"
            ),
            metric="weather_category",
            current_value=None,
            previous_value=None,
            threshold=None,
        ),
    ]
