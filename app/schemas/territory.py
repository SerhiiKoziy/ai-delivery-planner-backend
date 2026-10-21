"""Territory plan request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TerritorySolver = Literal["classical", "quantum_simulator", "ibm_emulator", "ibm_quantum"]


class TerritoryPlanRequest(BaseModel):
    delivery_ids: list[uuid.UUID] = Field(min_length=1)
    # One zone per vehicle, in this order: zone i belongs to vehicle_ids[i].
    vehicle_ids: list[uuid.UUID] = Field(min_length=1, max_length=32)
    solver: TerritorySolver = "quantum_simulator"
    balance_by: Literal["stops", "weight"] = "stops"
    # Penalty strength of "zones carry equal load" vs "keep neighbours together".
    balance_weight: float = Field(default=4.0, gt=0, le=100)
    qaoa_reps: int = Field(default=2, ge=1, le=5)
    shots: int = Field(default=2048, ge=100, le=20_000)


class TerritoryZone(BaseModel):
    index: int
    vehicle_id: uuid.UUID
    plate_number: str | None = None
    delivery_ids: list[uuid.UUID]
    stop_count: int
    load: float
    centroid_lat: float | None = None
    centroid_lng: float | None = None
    radius_km: float


class TerritoryPlanRead(BaseModel):
    id: uuid.UUID
    status: str
    solver: str
    balance_by: str
    num_zones: int
    num_deliveries: int
    zones: list[TerritoryZone]
    metrics: dict
    error: str | None = None
    total_ms: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
