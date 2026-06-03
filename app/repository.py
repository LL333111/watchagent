from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event, Reading
from app.schemas import EventCreate, ReadingCreate


def count_readings(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Reading)) or 0)


def count_events(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Event))) or 0


def list_readings(
    db: Session,
    city: str | None = None,
    limit: int = 50,
) -> list[Reading]:
    stmt = select(Reading).order_by(Reading.timestamp.desc(), Reading.id.desc()).limit(limit)
    if city is not None:
        stmt = stmt.where(Reading.city == city)
    return list(db.scalars(stmt).all())


def list_events(
    db: Session,
    city: str | None = None,
    limit: int = 50,
) -> list[Event]:
    stmt = select(Event).order_by(Event.timestamp.desc(), Event.id.desc()).limit(limit)
    if city is not None:
        stmt = stmt.where(Event.city == city)
    return list(db.scalars(stmt).all())


def get_latest_reading(db: Session, city: str) -> Reading | None:
    stmt = (
        select(Reading)
        .where(Reading.city == city)
        .order_by(Reading.timestamp.desc(), Reading.id.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def list_latest_readings_by_city(
    db: Session,
    city_names: tuple[str, ...],
) -> list[Reading]:
    readings: list[Reading] = []
    for city in city_names:
        latest = get_latest_reading(db, city)
        if latest is not None:
            readings.append(latest)
    return readings


def get_previous_reading(
    db: Session,
    city: str,
    before_timestamp: datetime,
) -> Reading | None:
    stmt = (
        select(Reading)
        .where(Reading.city == city, Reading.timestamp < before_timestamp)
        .order_by(Reading.timestamp.desc(), Reading.id.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def _get_reading_by_city_timestamp(
    db: Session,
    city: str,
    timestamp: datetime,
) -> Reading | None:
    stmt = select(Reading).where(
        Reading.city == city,
        Reading.timestamp == timestamp,
    )
    return db.scalar(stmt)


def _get_event_by_natural_key(
    db: Session,
    city: str,
    timestamp: datetime,
    event_type: str,
) -> Event | None:
    stmt = select(Event).where(
        Event.city == city,
        Event.timestamp == timestamp,
        Event.event_type == event_type,
    )
    return db.scalar(stmt)


def insert_reading_if_new(
    db: Session,
    reading_data: ReadingCreate,
) -> tuple[Reading, bool]:
    existing = _get_reading_by_city_timestamp(
        db,
        reading_data.city,
        reading_data.timestamp,
    )
    if existing is not None:
        return existing, False

    reading = Reading(**reading_data.model_dump())
    db.add(reading)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_reading_by_city_timestamp(
            db,
            reading_data.city,
            reading_data.timestamp,
        )
        if existing is None:
            raise
        return existing, False

    db.refresh(reading)
    return reading, True


def insert_event_if_new(
    db: Session,
    event_data: EventCreate,
) -> tuple[Event, bool]:
    existing = _get_event_by_natural_key(
        db,
        event_data.city,
        event_data.timestamp,
        event_data.event_type,
    )
    if existing is not None:
        return existing, False

    event = Event(**event_data.model_dump())
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_event_by_natural_key(
            db,
            event_data.city,
            event_data.timestamp,
            event_data.event_type,
        )
        if existing is None:
            raise
        return existing, False

    db.refresh(event)
    return event, True


def insert_events_if_new(
    db: Session,
    events: list[EventCreate],
) -> list[tuple[Event, bool]]:
    return [insert_event_if_new(db, event_data) for event_data in events]
