"""Delivery note model — free-text notes attached to a delivery.

Raw notes are parsed into structured JSON by services.ai.parser.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

# TODO: full schema (parsed_data JSON column, delivery relationship)


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id"))
    raw_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
