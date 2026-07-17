"""Route request/response schemas."""

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict


class OptimizeRequest(BaseModel):
    delivery_ids: list[uuid.UUID]
    vehicle_ids: list[uuid.UUID]
    depot_id: uuid.UUID
    return_to_depot: bool = True


class RouteStopRead(BaseModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    sequence: int
    estimated_arrival: time
    estimated_departure: time
    distance_from_previous_km: float

    model_config = ConfigDict(from_attributes=True)


class RouteRead(BaseModel):
    id: uuid.UUID
    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    depot_id: uuid.UUID
    status: str
    return_to_depot: bool
    total_distance_km: float
    total_duration_minutes: int
    created_at: datetime
    updated_at: datetime
    stops: list[RouteStopRead] = []

    model_config = ConfigDict(from_attributes=True)


class OptimizeResult(BaseModel):
    routes: list[RouteRead]
    unassigned_delivery_ids: list[uuid.UUID]
    skipped_not_geocoded: list[uuid.UUID]
    vehicles_without_driver: list[uuid.UUID]
