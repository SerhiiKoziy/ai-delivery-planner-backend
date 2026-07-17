"""Driver model — a working resource the route optimizer schedules against."""

import uuid
from datetime import UTC, datetime, time

from sqlalchemy import DateTime, Integer, String, Time, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active")
    working_hours_start: Mapped[time] = mapped_column(Time, default=time(8, 0))
    working_hours_end: Mapped[time] = mapped_column(Time, default=time(18, 0))
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True, default=time(13, 0))
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True, default=time(14, 0))
    max_working_minutes: Mapped[int] = mapped_column(Integer, default=600)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
