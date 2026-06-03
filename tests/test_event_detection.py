from datetime import datetime, timezone
from typing import Any

from app.event_detection import detect_city_events, detect_regional_events


def _reading(
    city: str = "Toronto",
    *,
    timestamp: datetime | None = None,
    temperature_2m: float = 10.0,
    apparent_temperature: float = 10.0,
    precipitation: float = 0.0,
    wind_speed_10m: float = 15.0,
    weather_code: int = 0,
    weather_category: str = "clear",
) -> dict[str, Any]:
    return {
        "city": city,
        "timestamp": timestamp or datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "temperature_2m": temperature_2m,
        "apparent_temperature": apparent_temperature,
        "precipitation": precipitation,
        "wind_speed_10m": wind_speed_10m,
        "weather_code": weather_code,
        "weather_category": weather_category,
    }


def _event_types(events: list[dict[str, Any]]) -> set[str]:
    return {event["event_type"] for event in events}


def test_first_reading_does_not_emit_bootstrap_events() -> None:
    current = _reading(temperature_2m=-2.0, apparent_temperature=-10.0)

    events = detect_city_events("Toronto", current, None)

    assert events == []


def test_large_temperature_swing_triggers() -> None:
    previous = _reading(temperature_2m=10.0)
    current = _reading(temperature_2m=16.5)

    events = detect_city_events("Toronto", current, previous)

    assert "temperature_swing" in _event_types(events)


def test_small_temperature_change_does_not_trigger() -> None:
    previous = _reading(temperature_2m=10.0)
    current = _reading(temperature_2m=13.0)

    events = detect_city_events("Toronto", current, previous)

    assert "temperature_swing" not in _event_types(events)


def test_temperature_swing_at_threshold_still_triggers() -> None:
    previous = _reading(temperature_2m=10.0)
    current = _reading(temperature_2m=15.0)

    events = detect_city_events("Toronto", current, previous)

    assert "temperature_swing" in _event_types(events)


def test_vancouver_uses_lower_temperature_threshold() -> None:
    previous = _reading(city="Vancouver", temperature_2m=10.0)
    current = _reading(city="Vancouver", temperature_2m=14.2)

    events = detect_city_events("Vancouver", current, previous)

    assert "temperature_swing" in _event_types(events)


def test_feels_like_stress_triggers_when_gap_enters_cold_stress_band() -> None:
    previous = _reading(temperature_2m=4.0, apparent_temperature=3.0)
    current = _reading(temperature_2m=3.0, apparent_temperature=-4.0)

    events = detect_city_events("Toronto", current, previous)

    assert "feels_like_stress" in _event_types(events)


def test_existing_feels_like_stress_does_not_repeat_without_a_new_transition() -> None:
    previous = _reading(temperature_2m=2.0, apparent_temperature=-5.0)
    current = _reading(temperature_2m=1.0, apparent_temperature=-6.5)

    events = detect_city_events("Toronto", current, previous)

    assert "feels_like_stress" not in _event_types(events)


def test_feels_like_stress_triggers_when_gap_enters_heat_stress_band() -> None:
    previous = _reading(temperature_2m=24.0, apparent_temperature=25.0)
    current = _reading(temperature_2m=28.0, apparent_temperature=34.0)

    events = detect_city_events("Toronto", current, previous)

    assert "feels_like_stress" in _event_types(events)


def test_freeze_thaw_transition_triggers_when_crossing_freezing() -> None:
    previous = _reading(temperature_2m=3.0, apparent_temperature=2.0)
    current = _reading(temperature_2m=-2.0, apparent_temperature=-5.0)

    events = detect_city_events("Toronto", current, previous)

    assert "freeze_thaw_transition" in _event_types(events)


def test_small_temperature_move_near_freezing_does_not_trigger_crossing_event() -> None:
    previous = _reading(temperature_2m=0.4, apparent_temperature=-1.0)
    current = _reading(temperature_2m=-0.6, apparent_temperature=-2.0)

    events = detect_city_events("Toronto", current, previous)

    assert "freeze_thaw_transition" not in _event_types(events)


def test_wind_spike_triggers_on_speed_and_increase() -> None:
    previous = _reading(wind_speed_10m=18.0)
    current = _reading(wind_speed_10m=35.0)

    events = detect_city_events("Toronto", current, previous)

    assert "wind_spike" in _event_types(events)


def test_high_wind_without_sharp_increase_does_not_trigger() -> None:
    previous = _reading(wind_speed_10m=30.0)
    current = _reading(wind_speed_10m=38.0)

    events = detect_city_events("Toronto", current, previous)

    assert "wind_spike" not in _event_types(events)


def test_precipitation_started_requires_a_real_dry_to_wet_transition() -> None:
    previous = _reading(precipitation=0.0, weather_category="cloudy")
    current = _reading(precipitation=0.6, weather_category="rain")

    events = detect_city_events("Toronto", current, previous)

    assert "precipitation_started" in _event_types(events)


def test_trace_precipitation_does_not_trigger_an_event() -> None:
    previous = _reading(precipitation=0.0, weather_category="cloudy")
    current = _reading(precipitation=0.1, weather_category="cloudy")

    events = detect_city_events("Toronto", current, previous)

    assert "precipitation_started" not in _event_types(events)


def test_precipitation_started_can_trigger_on_weather_category_even_below_threshold() -> None:
    previous = _reading(precipitation=0.0, weather_category="cloudy")
    current = _reading(precipitation=0.1, weather_category="rain")

    events = detect_city_events("Toronto", current, previous)

    assert "precipitation_started" in _event_types(events)


def test_weather_regime_shift_triggers_for_clear_to_severe() -> None:
    previous = _reading(weather_category="clear")
    current = _reading(weather_category="rain")

    events = detect_city_events("Toronto", current, previous)

    assert "weather_regime_shift" in _event_types(events)


def test_minor_clear_cloudy_changes_do_not_trigger_transition() -> None:
    previous = _reading(weather_category="clear")
    current = _reading(weather_category="cloudy")

    events = detect_city_events("Toronto", current, previous)

    assert "weather_regime_shift" not in _event_types(events)


def test_weather_regime_shift_triggers_for_rain_to_snow() -> None:
    previous = _reading(weather_category="rain")
    current = _reading(weather_category="snow")

    events = detect_city_events("Toronto", current, previous)

    assert "weather_regime_shift" in _event_types(events)


def test_parked_vehicle_heat_risk_triggers_when_heat_window_develops() -> None:
    previous = _reading(temperature_2m=24.0, apparent_temperature=25.0)
    current = _reading(temperature_2m=27.0, apparent_temperature=29.0, weather_category="clear")

    events = detect_city_events("Toronto", current, previous)

    assert "parked_vehicle_heat_risk" in _event_types(events)


def test_parked_vehicle_heat_risk_does_not_repeat_when_already_active() -> None:
    previous = _reading(temperature_2m=27.0, apparent_temperature=29.0, weather_category="clear")
    current = _reading(temperature_2m=28.0, apparent_temperature=30.0, weather_category="clear")

    events = detect_city_events("Toronto", current, previous)

    assert "parked_vehicle_heat_risk" not in _event_types(events)


def test_skin_exposure_stress_triggers_on_cold_wind_entry() -> None:
    previous = _reading(apparent_temperature=1.0, wind_speed_10m=15.0)
    current = _reading(apparent_temperature=-2.0, wind_speed_10m=24.0)

    events = detect_city_events("Toronto", current, previous)

    assert "skin_exposure_stress" in _event_types(events)


def test_skin_exposure_stress_does_not_repeat_when_already_active() -> None:
    previous = _reading(apparent_temperature=-2.0, wind_speed_10m=24.0)
    current = _reading(apparent_temperature=-3.0, wind_speed_10m=26.0)

    events = detect_city_events("Toronto", current, previous)

    assert "skin_exposure_stress" not in _event_types(events)


def test_toronto_transit_weather_risk_triggers_on_precipitation_shift() -> None:
    previous = _reading(city="Toronto", precipitation=0.0, weather_category="cloudy")
    current = _reading(city="Toronto", precipitation=0.4, weather_category="rain")

    events = detect_city_events("Toronto", current, previous)

    assert "toronto_transit_weather_risk" in _event_types(events)


def test_toronto_transit_weather_risk_is_city_specific() -> None:
    previous = _reading(city="Ottawa", precipitation=0.0, weather_category="cloudy")
    current = _reading(city="Ottawa", precipitation=0.4, weather_category="rain")

    events = detect_city_events("Ottawa", current, previous)

    assert "toronto_transit_weather_risk" not in _event_types(events)


def test_ottawa_surface_ice_risk_triggers_on_wet_near_freezing_conditions() -> None:
    previous = _reading(city="Ottawa", temperature_2m=3.0, precipitation=0.0, weather_category="cloudy")
    current = _reading(city="Ottawa", temperature_2m=0.5, precipitation=0.2, weather_category="rain")

    events = detect_city_events("Ottawa", current, previous)

    assert "ottawa_surface_ice_risk" in _event_types(events)


def test_ottawa_surface_ice_risk_does_not_duplicate_freeze_thaw_transition() -> None:
    previous = _reading(city="Ottawa", temperature_2m=2.0, precipitation=0.0)
    current = _reading(city="Ottawa", temperature_2m=-2.0, precipitation=0.4, weather_category="rain")

    events = detect_city_events("Ottawa", current, previous)

    assert "freeze_thaw_transition" in _event_types(events)
    assert "ottawa_surface_ice_risk" not in _event_types(events)


def test_vancouver_coastal_rain_wind_exposure_triggers_on_windy_rain() -> None:
    previous = _reading(city="Vancouver", wind_speed_10m=12.0, weather_category="cloudy")
    current = _reading(city="Vancouver", wind_speed_10m=27.0, weather_category="rain")

    events = detect_city_events("Vancouver", current, previous)

    assert "vancouver_coastal_rain_wind_exposure" in _event_types(events)


def test_vancouver_coastal_rain_wind_exposure_is_city_specific() -> None:
    previous = _reading(city="Toronto", wind_speed_10m=12.0, weather_category="cloudy")
    current = _reading(city="Toronto", wind_speed_10m=27.0, weather_category="rain")

    events = detect_city_events("Toronto", current, previous)

    assert "vancouver_coastal_rain_wind_exposure" not in _event_types(events)


def test_low_visibility_commute_window_triggers_when_bad_weather_enters_commute_time() -> None:
    previous = _reading(
        city="Toronto",
        timestamp=datetime(2026, 1, 1, 19, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )
    current = _reading(
        city="Toronto",
        timestamp=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )

    events = detect_city_events("Toronto", current, previous)

    assert "low_visibility_commute_window" in _event_types(events)


def test_low_visibility_commute_window_uses_vancouver_local_time() -> None:
    previous = _reading(
        city="Vancouver",
        timestamp=datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )
    current = _reading(
        city="Vancouver",
        timestamp=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )

    events = detect_city_events("Vancouver", current, previous)

    assert "low_visibility_commute_window" in _event_types(events)


def test_low_visibility_commute_window_is_distinct_from_precipitation_start() -> None:
    previous = _reading(
        city="Toronto",
        timestamp=datetime(2026, 1, 1, 19, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )
    current = _reading(
        city="Toronto",
        timestamp=datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
        precipitation=0.4,
        weather_category="rain",
    )

    events = detect_city_events("Toronto", current, previous)

    assert "low_visibility_commute_window" in _event_types(events)
    assert "precipitation_started" not in _event_types(events)


def test_outdoor_recovery_window_triggers_after_bad_weather_clears() -> None:
    previous = _reading(
        precipitation=0.5,
        wind_speed_10m=36.0,
        apparent_temperature=2.0,
        weather_category="rain",
    )
    current = _reading(
        precipitation=0.0,
        wind_speed_10m=12.0,
        apparent_temperature=18.0,
        weather_category="clear",
    )

    events = detect_city_events("Toronto", current, previous)

    assert "outdoor_recovery_window" in _event_types(events)


def test_outdoor_recovery_window_does_not_repeat_during_stable_good_weather() -> None:
    previous = _reading(
        precipitation=0.0,
        wind_speed_10m=12.0,
        apparent_temperature=18.0,
        weather_category="clear",
    )
    current = _reading(
        precipitation=0.0,
        wind_speed_10m=13.0,
        apparent_temperature=19.0,
        weather_category="cloudy",
    )

    events = detect_city_events("Toronto", current, previous)

    assert "outdoor_recovery_window" not in _event_types(events)


def test_regional_weather_advantage_triggers_for_clear_city_against_bad_weather_elsewhere() -> None:
    readings = [
        _reading(city="Ottawa", apparent_temperature=18.0, precipitation=0.0, wind_speed_10m=8.0, weather_category="clear"),
        _reading(city="Toronto", apparent_temperature=12.0, precipitation=0.7, wind_speed_10m=18.0, weather_category="rain"),
        _reading(city="Vancouver", apparent_temperature=4.0, precipitation=0.4, wind_speed_10m=36.0, weather_category="storm"),
    ]

    events = detect_regional_events(readings)

    assert "regional_weather_advantage" in _event_types(events)
    assert events[0]["city"] == "Ottawa"


def test_regional_weather_advantage_requires_a_clear_score_gap() -> None:
    readings = [
        _reading(city="Ottawa", apparent_temperature=18.0, precipitation=0.0, wind_speed_10m=8.0, weather_category="clear"),
        _reading(city="Toronto", apparent_temperature=18.0, precipitation=0.0, wind_speed_10m=9.0, weather_category="clear"),
        _reading(city="Vancouver", apparent_temperature=17.0, precipitation=0.0, wind_speed_10m=10.0, weather_category="cloudy"),
    ]

    events = detect_regional_events(readings)

    assert events == []
