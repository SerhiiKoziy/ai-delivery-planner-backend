"""RouteStop model — an ordered stop within a Route, mapped from a Delivery."""

import uuid
from datetime import UTC, datetime, time

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Time, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

# TODO: full schema (actual arrival, route/delivery relationships)


class RouteStop(Base):
    __tablename__ = "route_stops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("routes.id"))
    delivery_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("deliveries.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    estimated_arrival: Mapped[time] = mapped_column(Time)
    estimated_departure: Mapped[time] = mapped_column(Time)
    distance_from_previous_km: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
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
