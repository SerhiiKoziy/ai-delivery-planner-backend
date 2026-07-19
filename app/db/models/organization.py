"""Organization model — the tenant/business account."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.plans import DEFAULT_SUBSCRIPTION_PLAN, SubscriptionPlan
from app.db.models.base import Base

# TODO: full schema (settings, relationships)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, native_enum=False, length=20, validate_strings=True),
        default=DEFAULT_SUBSCRIPTION_PLAN,
        server_default=DEFAULT_SUBSCRIPTION_PLAN.value,
    )
    routes_generated_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    geocode_calls_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ai_calls_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
