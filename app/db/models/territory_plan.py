"""TerritoryPlan model — a split of deliveries into stable per-vehicle zones."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class TerritoryPlan(Base):
    __tablename__ = "territory_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="running")
    solver: Mapped[str] = mapped_column(String(32))
    balance_by: Mapped[str] = mapped_column(String(32), default="stops")
    num_zones: Mapped[int] = mapped_column(Integer)
    num_deliveries: Mapped[int] = mapped_column(Integer, default=0)
    # [{index, vehicle_id, delivery_ids, stop_count, load, centroid_lat,
    #   centroid_lng, radius_km}] — small (one entry per vehicle), always read
    # whole, so a JSON column beats a child table here.
    zones: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
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
