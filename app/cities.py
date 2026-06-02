from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class CityConfig:
    name: str
    lat: float
    lon: float
    climate_profile: str
    temperature_swing_threshold: float


CITIES: Final[dict[str, CityConfig]] = {
    "Ottawa": CityConfig(
        name="Ottawa",
        lat=45.42,
        lon=-75.69,
        climate_profile="continental",
        temperature_swing_threshold=6.0,
    ),
    "Toronto": CityConfig(
        name="Toronto",
        lat=43.70,
        lon=-79.42,
        climate_profile="great_lakes",
        temperature_swing_threshold=5.0,
    ),
    "Vancouver": CityConfig(
        name="Vancouver",
        lat=49.25,
        lon=-123.12,
        climate_profile="coastal",
        temperature_swing_threshold=4.0,
    ),
}


def get_city(name: str) -> CityConfig | None:
    return CITIES.get(name)
