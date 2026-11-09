"""User model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.roles import DEFAULT_USER_ROLE, UserRole
from app.db.models.base import Base

# TODO: full schema (relationships)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))
    # New signups default to False at the Python/app level (set explicitly on
    # every INSERT the app issues); `server_default=true()` only backfills
    # rows that already existed before this column was added, grandfathering
    # them in rather than locking out every pre-existing account.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=true())
    # Stored by `.value` ("user"/"admin"), like Organization.subscription_plan.
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            native_enum=False,
            length=20,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=DEFAULT_USER_ROLE,
        server_default=DEFAULT_USER_ROLE.value,
    )
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
