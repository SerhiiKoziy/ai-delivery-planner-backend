"""Vehicle request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleCreate(BaseModel):
    plate_number: str
    status: str = "active"
    capacity_weight_kg: float = 0.0
    capacity_volume_m3: float = 0.0
    driver_id: uuid.UUID | None = None


class VehicleUpdate(BaseModel):
    plate_number: str | None = None
    status: str | None = None
    capacity_weight_kg: float | None = None
    capacity_volume_m3: float | None = None
    driver_id: uuid.UUID | None = None


class VehicleRead(BaseModel):
    id: uuid.UUID
    plate_number: str
    status: str
    capacity_weight_kg: float
    capacity_volume_m3: float
    driver_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
