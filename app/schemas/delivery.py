"""Delivery request/response schemas."""

from pydantic import BaseModel


class DeliveryCreate(BaseModel):
    address: str
    notes: str | None = None


class DeliveryRead(BaseModel):
    id: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    status: str


class DeliveryImportRow(BaseModel):
    """A single raw row from an imported Excel/CSV delivery list, pre-cleanup."""

    raw_address: str
    raw_notes: str | None = None
