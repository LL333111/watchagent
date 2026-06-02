from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReadingBase(BaseModel):
    city: str
    timestamp: datetime
    temperature_2m: float
    apparent_temperature: float
    precipitation: float
    wind_speed_10m: float
    weather_code: int
    weather_category: str


class ReadingCreate(ReadingBase):
    pass


class ReadingOut(ReadingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ReadingsResponse(BaseModel):
    readings: list[ReadingOut]


class EventBase(BaseModel):
    city: str
    timestamp: datetime
    event_type: str
    severity: str
    message: str
    reason: str
    metric: str
    current_value: float | None = None
    previous_value: float | None = None
    threshold: float | None = None
    reading_id: int | None = None


class EventCreate(EventBase):
    pass


class EventOut(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class EventsResponse(BaseModel):
    events: list[EventOut]


class HealthResponse(BaseModel):
    status: str = "ok"
    readings_stored: int
    events_stored: int
