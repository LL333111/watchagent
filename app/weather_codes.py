from typing import Literal

WeatherCategory = Literal[
    "clear",
    "cloudy",
    "fog",
    "rain",
    "snow",
    "storm",
    "unknown",
]


def categorize_weather_code(code: int) -> WeatherCategory:
    """Map WMO weather_code (Open-Meteo) to a broad category."""
    if code == 0:
        return "clear"
    if code in {1, 2, 3}:
        return "cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "storm"
    return "unknown"
