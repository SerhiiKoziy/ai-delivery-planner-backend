"""Delivery model — a single stop to be routed."""

import uuid
from datetime import UTC, datetime, time
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class DeliveryPriority(str, Enum):
    """Business priority tier for a delivery stop."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    VIP = "vip"


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))
    customer_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str] = mapped_column(String(500))
    order_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[DeliveryPriority] = mapped_column(
        SAEnum(DeliveryPriority, native_enum=False),
        default=DeliveryPriority.NORMAL,
    )
    unloading_minutes: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    volume_m3: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    delivery_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    delivery_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending_geocode")
    # Client-side `default` (microsecond precision, computed in Python) is used
    # for ORM-driven inserts/updates so ordering by created_at is deterministic
    # even on backends (e.g. SQLite's CURRENT_TIMESTAMP) with coarser server-side
    # clock resolution. `server_default`/`onupdate` remain as DB-level fallbacks
    # for inserts/updates issued outside the ORM (raw SQL, other clients).
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
