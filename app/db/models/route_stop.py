"""RouteStop model — an ordered stop within a Route, mapped from a Delivery."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

# TODO: full schema (eta, actual arrival, route/delivery relationships)


class RouteStop(Base):
    __tablename__ = "route_stops"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.id"))
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
