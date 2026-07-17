"""Depot request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DepotCreate(BaseModel):
    address: str
    latitude: float
    longitude: float


class DepotUpdate(BaseModel):
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class DepotRead(BaseModel):
    id: uuid.UUID
    address: str
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
