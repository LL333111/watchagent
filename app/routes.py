from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import repository
from app.db import get_db
from app.schemas import EventsResponse, HealthResponse, ReadingsResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    return HealthResponse(
        readings_stored=repository.count_readings(db),
        events_stored=repository.count_events(db),
    )


@router.get("/readings", response_model=ReadingsResponse)
def get_readings(
    city: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ReadingsResponse:
    readings = repository.list_readings(db, city=city, limit=limit)
    return ReadingsResponse.model_validate({"readings": readings})


@router.get("/events", response_model=EventsResponse)
def get_events(
    city: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> EventsResponse:
    events = repository.list_events(db, city=city, limit=limit)
    return EventsResponse.model_validate({"events": events})
