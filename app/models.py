from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (
        UniqueConstraint("city", "timestamp", name="uq_readings_city_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_2m: Mapped[float] = mapped_column(Float, nullable=False)
    apparent_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    precipitation: Mapped[float] = mapped_column(Float, nullable=False)
    wind_speed_10m: Mapped[float] = mapped_column(Float, nullable=False)
    weather_code: Mapped[int] = mapped_column(Integer, nullable=False)
    weather_category: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    events: Mapped[list["Event"]] = relationship(back_populates="reading")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint(
            "city",
            "timestamp",
            "event_type",
            name="uq_events_city_timestamp_event_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    reading_id: Mapped[int | None] = mapped_column(
        ForeignKey("readings.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    reading: Mapped[Reading | None] = relationship(back_populates="events")
