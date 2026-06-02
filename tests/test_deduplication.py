from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repository
from app.models import Event, Reading
from app.schemas import EventCreate, ReadingCreate


def test_reading_deduplication(
    db_session: Session,
    reading_payload: dict[str, object],
) -> None:
    first, inserted_first = repository.insert_reading_if_new(
        db_session,
        ReadingCreate(**reading_payload),
    )
    second, inserted_second = repository.insert_reading_if_new(
        db_session,
        ReadingCreate(**reading_payload),
    )

    assert inserted_first is True
    assert inserted_second is False
    assert first.id == second.id
    assert repository.count_readings(db_session) == 1

    rows = list(db_session.scalars(select(Reading)).all())
    assert len(rows) == 1


def test_event_deduplication(
    db_session: Session,
    event_payload: dict[str, object],
) -> None:
    first, inserted_first = repository.insert_event_if_new(
        db_session,
        EventCreate(**event_payload),
    )
    second, inserted_second = repository.insert_event_if_new(
        db_session,
        EventCreate(**event_payload),
    )

    assert inserted_first is True
    assert inserted_second is False
    assert first.id == second.id
    assert repository.count_events(db_session) == 1

    rows = list(db_session.scalars(select(Event)).all())
    assert len(rows) == 1


def test_insert_reading_if_new_reports_insert_flags(
    db_session: Session,
    reading_payload: dict[str, object],
) -> None:
    _, first_inserted = repository.insert_reading_if_new(
        db_session,
        ReadingCreate(**reading_payload),
    )
    _, second_inserted = repository.insert_reading_if_new(
        db_session,
        ReadingCreate(**reading_payload),
    )

    assert first_inserted is True
    assert second_inserted is False


def test_insert_event_if_new_reports_insert_flags(
    db_session: Session,
    event_payload: dict[str, object],
) -> None:
    _, first_inserted = repository.insert_event_if_new(
        db_session,
        EventCreate(**event_payload),
    )
    _, second_inserted = repository.insert_event_if_new(
        db_session,
        EventCreate(**event_payload),
    )

    assert first_inserted is True
    assert second_inserted is False
