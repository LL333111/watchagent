from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

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
PARKED_VEHICLE_HEAT_TEMP = 26.0
SKIN_EXPOSURE_WIND = 20.0
VANCOUVER_COASTAL_WIND = 25.0
REGIONAL_ADVANTAGE_MIN_GAP = 4.0
OUTDOOR_RECOVERY_MAX_WIND = 25.0
OUTDOOR_RECOVERY_MIN_APPARENT = 5.0
OUTDOOR_RECOVERY_MAX_APPARENT = 27.0
COMMUTE_START_HOUR = 15
COMMUTE_END_HOUR = 18

CITY_TIME_ZONES = {
    "Ottawa": ZoneInfo("America/Toronto"),
    "Toronto": ZoneInfo("America/Toronto"),
    "Vancouver": ZoneInfo("America/Vancouver"),
}


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
    events.extend(
        _detect_life_impact_events(
            city,
            timestamp,
            current_reading,
            previous_reading,
        ),
    )
    return events


def detect_regional_events(
    latest_readings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(latest_readings) < len(CITIES):
        return []

    ranked = sorted(
        latest_readings,
        key=_regional_weather_score,
        reverse=True,
    )
    best = ranked[0]
    runner_up = ranked[1]
    worst = ranked[-1]
    score_gap = _regional_weather_score(best) - _regional_weather_score(runner_up)

    if score_gap < REGIONAL_ADVANTAGE_MIN_GAP:
        return []
    if not _has_easy_weather_window(best) or not _has_notable_weather_friction(worst):
        return []

    best_city = str(best["city"])
    worst_city = str(worst["city"])
    return [
        _base_event(
            city=best_city,
            timestamp=best["timestamp"],
            event_type="regional_weather_advantage",
            severity="moderate",
            message=(
                f"{best_city} has the clearest weather window across the monitored "
                f"cities while {worst_city} is dealing with more friction"
            ),
            reason=(
                "cross-city comparison can matter when family, friends, or plans "
                "span more than one monitored city"
            ),
            metric="regional_weather_score",
            current_value=_regional_weather_score(best),
            previous_value=_regional_weather_score(runner_up),
            threshold=REGIONAL_ADVANTAGE_MIN_GAP,
        ),
    ]


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


def _transitioned_into(current_active: bool, previous_active: bool) -> bool:
    return current_active and not previous_active


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


def _detect_life_impact_events(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    events.extend(_detect_parked_vehicle_heat_risk(city, timestamp, current, previous))
    events.extend(_detect_skin_exposure_stress(city, timestamp, current, previous))
    events.extend(_detect_low_visibility_commute_window(city, timestamp, current, previous))
    events.extend(_detect_outdoor_recovery_window(city, timestamp, current, previous))
    if city == "Toronto":
        events.extend(_detect_toronto_transit_weather_risk(city, timestamp, current, previous))
    if city == "Ottawa":
        events.extend(_detect_ottawa_surface_ice_risk(city, timestamp, current, previous))
    if city == "Vancouver":
        events.extend(_detect_vancouver_coastal_rain_wind_exposure(city, timestamp, current, previous))
    return events


def _is_low_visibility_weather(reading: dict[str, Any]) -> bool:
    return (
        str(reading["weather_category"]) in IMPACTFUL_CATEGORIES
        or float(reading["precipitation"]) >= MIN_NOTABLE_PRECIPITATION
    )


def _is_local_commute_window(city: str, timestamp: Any) -> bool:
    time_zone = CITY_TIME_ZONES.get(city)
    if time_zone is None:
        return False
    local_timestamp = _coerce_datetime(timestamp).astimezone(time_zone)
    return COMMUTE_START_HOUR <= local_timestamp.hour < COMMUTE_END_HOUR


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError(f"expected datetime or ISO timestamp string, got {type(value)!r}")

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _is_bad_weather_window(reading: dict[str, Any]) -> bool:
    return (
        str(reading["weather_category"]) in IMPACTFUL_CATEGORIES
        or float(reading["precipitation"]) >= MIN_NOTABLE_PRECIPITATION
        or float(reading["wind_speed_10m"]) >= WIND_SPIKE_MIN_SPEED
        or _stress_band(float(reading["apparent_temperature"])) != "neutral"
    )


def _is_easy_outdoor_window(reading: dict[str, Any]) -> bool:
    apparent = float(reading["apparent_temperature"])
    return (
        str(reading["weather_category"]) in CLEAR_CLOUDY
        and float(reading["precipitation"]) <= 0.05
        and float(reading["wind_speed_10m"]) < OUTDOOR_RECOVERY_MAX_WIND
        and OUTDOOR_RECOVERY_MIN_APPARENT <= apparent <= OUTDOOR_RECOVERY_MAX_APPARENT
    )


def _detect_low_visibility_commute_window(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_active = (
        _is_local_commute_window(city, timestamp)
        and _is_low_visibility_weather(current)
    )
    previous_active = (
        _is_local_commute_window(city, previous["timestamp"])
        and _is_low_visibility_weather(previous)
    )
    if not _transitioned_into(current_active, previous_active):
        return []

    category = str(current["weather_category"])
    precipitation = float(current["precipitation"])
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="low_visibility_commute_window",
            severity="high" if category in {"snow", "storm", "fog"} else "moderate",
            message=(
                f"Low-visibility commute window opened in {city}: "
                f"{category} with {precipitation:.1f} mm precipitation"
            ),
            reason=(
                "wet, foggy, snowy, or stormy conditions are more actionable "
                "when they overlap the local afternoon commute window"
            ),
            metric="weather_category",
            current_value=None,
            previous_value=None,
            threshold=None,
        ),
    ]


def _detect_outdoor_recovery_window(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_active = _is_easy_outdoor_window(current)
    previous_active = _is_easy_outdoor_window(previous)
    if not current_active or previous_active or not _is_bad_weather_window(previous):
        return []

    apparent = float(current["apparent_temperature"])
    wind = float(current["wind_speed_10m"])
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="outdoor_recovery_window",
            severity="low",
            message=(
                f"Outdoor conditions recovered in {city}: dry, usable weather "
                f"with feels-like {apparent:.1f}C and {wind:.1f} km/h wind"
            ),
            reason=(
                "the city moved from a poor weather state into a dry, moderate, "
                "low-wind window that is useful for walking, errands, and plans"
            ),
            metric="apparent_temperature",
            current_value=apparent,
            previous_value=float(previous["apparent_temperature"]),
            threshold=OUTDOOR_RECOVERY_MIN_APPARENT,
        ),
    ]


def _detect_parked_vehicle_heat_risk(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_temp = float(current["temperature_2m"])
    current_apparent = float(current["apparent_temperature"])
    previous_temp = float(previous["temperature_2m"])
    previous_apparent = float(previous["apparent_temperature"])
    current_category = str(current["weather_category"])
    previous_category = str(previous["weather_category"])
    current_active = (
        current_apparent >= HEAT_STRESS_BOUNDARY
        or (current_temp >= PARKED_VEHICLE_HEAT_TEMP and current_category in CLEAR_CLOUDY)
    )
    previous_active = (
        previous_apparent >= HEAT_STRESS_BOUNDARY
        or (previous_temp >= PARKED_VEHICLE_HEAT_TEMP and previous_category in CLEAR_CLOUDY)
    )
    if not _transitioned_into(current_active, previous_active):
        return []

    severity = "high" if current_apparent >= 35.0 or current_temp >= 30.0 else "moderate"
    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="parked_vehicle_heat_risk",
            severity=severity,
            message=(
                f"Parked vehicle heat risk increased in {city}: air temperature "
                f"{current_temp:.1f}C, feels like {current_apparent:.1f}C"
            ),
            reason=(
                "sunny or warm conditions can make parked vehicles heat quickly, "
                "which matters for children, pets, and vulnerable passengers"
            ),
            metric="apparent_temperature",
            current_value=current_apparent,
            previous_value=previous_apparent,
            threshold=HEAT_STRESS_BOUNDARY,
        ),
    ]


def _detect_skin_exposure_stress(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_apparent = float(current["apparent_temperature"])
    previous_apparent = float(previous["apparent_temperature"])
    current_wind = float(current["wind_speed_10m"])
    previous_wind = float(previous["wind_speed_10m"])
    current_active = current_apparent <= COLD_STRESS_BOUNDARY and current_wind >= SKIN_EXPOSURE_WIND
    previous_active = previous_apparent <= COLD_STRESS_BOUNDARY and previous_wind >= SKIN_EXPOSURE_WIND
    if not _transitioned_into(current_active, previous_active):
        return []

    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="skin_exposure_stress",
            severity="moderate" if current_apparent > -10.0 else "high",
            message=(
                f"Cold wind exposure increased in {city}: feels like "
                f"{current_apparent:.1f}C with {current_wind:.1f} km/h wind"
            ),
            reason=(
                "cold apparent temperature combined with wind can make exposed "
                "skin feel harsher than the air temperature alone suggests"
            ),
            metric="apparent_temperature",
            current_value=current_apparent,
            previous_value=previous_apparent,
            threshold=COLD_STRESS_BOUNDARY,
        ),
    ]


def _detect_toronto_transit_weather_risk(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_category = str(current["weather_category"])
    previous_category = str(previous["weather_category"])
    current_precip = float(current["precipitation"])
    previous_precip = float(previous["precipitation"])
    current_wind = float(current["wind_speed_10m"])
    previous_wind = float(previous["wind_speed_10m"])
    current_active = (
        current_category in PRECIPITATION_CATEGORIES
        or current_precip >= MIN_NOTABLE_PRECIPITATION
        or current_wind >= WIND_SPIKE_MIN_SPEED
    )
    previous_active = (
        previous_category in PRECIPITATION_CATEGORIES
        or previous_precip >= MIN_NOTABLE_PRECIPITATION
        or previous_wind >= WIND_SPIKE_MIN_SPEED
    )
    if not _transitioned_into(current_active, previous_active):
        return []

    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="toronto_transit_weather_risk",
            severity="high" if current_category in {"snow", "storm"} else "moderate",
            message=f"Transit weather risk increased in Toronto as conditions shifted to {current_category}",
            reason=(
                "Toronto surface transit is more exposed to snow, freezing rain, "
                "heavy precipitation, and strong wind than underground service alone"
            ),
            metric="weather_category",
            current_value=None,
            previous_value=None,
            threshold=None,
        ),
    ]


def _detect_ottawa_surface_ice_risk(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_temp = float(current["temperature_2m"])
    previous_temp = float(previous["temperature_2m"])
    current_precip = float(current["precipitation"])
    previous_precip = float(previous["precipitation"])
    current_category = str(current["weather_category"])
    previous_category = str(previous["weather_category"])
    current_active = (
        current_temp <= FREEZE_MARGIN
        and (current_precip > 0.0 or current_category in PRECIPITATION_CATEGORIES)
    )
    previous_active = (
        previous_temp <= FREEZE_MARGIN
        and (previous_precip > 0.0 or previous_category in PRECIPITATION_CATEGORIES)
    )
    freeze_thaw_already_explains_change = (
        previous_temp >= FREEZE_MARGIN and current_temp <= -FREEZE_MARGIN
    )
    if freeze_thaw_already_explains_change:
        return []
    if not _transitioned_into(current_active, previous_active):
        return []

    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="ottawa_surface_ice_risk",
            severity="high",
            message=(
                f"Surface ice risk increased in Ottawa near freezing "
                f"({previous_temp:.1f}C -> {current_temp:.1f}C)"
            ),
            reason=(
                "near-freezing precipitation is especially relevant for Ottawa "
                "roads, sidewalks, pathways, and winter surface conditions"
            ),
            metric="temperature_2m",
            current_value=current_temp,
            previous_value=previous_temp,
            threshold=FREEZE_MARGIN,
        ),
    ]


def _detect_vancouver_coastal_rain_wind_exposure(
    city: str,
    timestamp: datetime,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[dict[str, Any]]:
    current_category = str(current["weather_category"])
    previous_category = str(previous["weather_category"])
    current_wind = float(current["wind_speed_10m"])
    previous_wind = float(previous["wind_speed_10m"])
    current_active = current_category in PRECIPITATION_CATEGORIES and current_wind >= VANCOUVER_COASTAL_WIND
    previous_active = previous_category in PRECIPITATION_CATEGORIES and previous_wind >= VANCOUVER_COASTAL_WIND
    if not _transitioned_into(current_active, previous_active):
        return []

    return [
        _base_event(
            city=city,
            timestamp=timestamp,
            event_type="vancouver_coastal_rain_wind_exposure",
            severity="high" if current_category == "storm" else "moderate",
            message=(
                f"Coastal rain and wind exposure increased in Vancouver: "
                f"{current_category} with {current_wind:.1f} km/h wind"
            ),
            reason=(
                "Vancouver coastal routes and exposed outdoor spaces are more "
                "sensitive to rain when wind is also elevated"
            ),
            metric="wind_speed_10m",
            current_value=current_wind,
            previous_value=previous_wind,
            threshold=VANCOUVER_COASTAL_WIND,
        ),
    ]


def _regional_weather_score(reading: dict[str, Any]) -> float:
    category = str(reading["weather_category"])
    precipitation = float(reading["precipitation"])
    wind = float(reading["wind_speed_10m"])
    apparent = float(reading["apparent_temperature"])

    score = 0.0
    if category in CLEAR_CLOUDY:
        score += 4.0
    elif category == "fog":
        score -= 1.0
    elif category == "rain":
        score -= 3.0
    elif category == "snow":
        score -= 4.0
    elif category == "storm":
        score -= 6.0

    if precipitation <= 0.05:
        score += 2.0
    elif precipitation >= MIN_NOTABLE_PRECIPITATION:
        score -= min(4.0, precipitation * 2.0)

    if wind < 15.0:
        score += 1.0
    elif wind >= WIND_SPIKE_MIN_SPEED:
        score -= 3.0
    elif wind >= 25.0:
        score -= 1.5

    if 10.0 <= apparent <= 25.0:
        score += 2.0
    elif 5.0 <= apparent < 10.0 or 25.0 < apparent <= 30.0:
        score += 0.5
    else:
        score -= 2.0

    return round(score, 2)


def _has_easy_weather_window(reading: dict[str, Any]) -> bool:
    return (
        str(reading["weather_category"]) in CLEAR_CLOUDY
        and float(reading["precipitation"]) <= 0.05
        and float(reading["wind_speed_10m"]) < 25.0
    )


def _has_notable_weather_friction(reading: dict[str, Any]) -> bool:
    return (
        str(reading["weather_category"]) in IMPACTFUL_CATEGORIES
        or float(reading["precipitation"]) >= MIN_NOTABLE_PRECIPITATION
        or float(reading["wind_speed_10m"]) >= WIND_SPIKE_MIN_SPEED
        or _stress_band(float(reading["apparent_temperature"])) != "neutral"
    )
