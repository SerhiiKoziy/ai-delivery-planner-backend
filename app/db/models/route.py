"""Route model — an optimized multi-stop plan for a single driver/vehicle."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

# TODO: full schema (driver/vehicle relationships, total distance/duration)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
