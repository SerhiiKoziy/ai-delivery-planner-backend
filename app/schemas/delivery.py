"""Delivery request/response schemas."""

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict

from app.db.models.delivery import DeliveryPriority

__all__ = [
    "DeliveryPriority",
    "DeliveryCreate",
    "DeliveryUpdate",
    "DeliveryRead",
    "DeliveryImportRow",
    "DeliveryImportRowResult",
    "DeliveryImportResult",
]


class DeliveryCreate(BaseModel):
    customer_name: str
    phone: str | None = None
    address: str
    order_number: str | None = None
    priority: DeliveryPriority = DeliveryPriority.NORMAL
    unloading_minutes: int = 0
    delivery_window_start: time | None = None
    delivery_window_end: time | None = None
    notes: str | None = None

    model_config = ConfigDict(use_enum_values=False)


class DeliveryUpdate(BaseModel):
    customer_name: str | None = None
    phone: str | None = None
    address: str | None = None
    order_number: str | None = None
    priority: DeliveryPriority | None = None
    unloading_minutes: int | None = None
    delivery_window_start: time | None = None
    delivery_window_end: time | None = None
    notes: str | None = None

    model_config = ConfigDict(use_enum_values=False)


class DeliveryRead(BaseModel):
    id: uuid.UUID
    customer_name: str
    phone: str | None = None
    address: str
    order_number: str | None = None
    priority: DeliveryPriority
    unloading_minutes: int
    delivery_window_start: time | None = None
    delivery_window_end: time | None = None
    notes: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryImportRow(BaseModel):
    """The normalized/validated shape of one imported row."""

    customer_name: str
    phone: str | None = None
    address: str
    order_number: str | None = None
    priority: DeliveryPriority = DeliveryPriority.NORMAL
    unloading_minutes: int = 0
    delivery_window_start: time | None = None
    delivery_window_end: time | None = None
    notes: str | None = None


class DeliveryImportRowResult(BaseModel):
    row_number: int
    success: bool
    delivery: DeliveryRead | None = None
    error: str | None = None


class DeliveryImportResult(BaseModel):
    total_rows: int
    imported: int
    failed: int
    rows: list[DeliveryImportRowResult]
