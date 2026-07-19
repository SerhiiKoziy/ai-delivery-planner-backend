"""Route request/response schemas."""

import uuid
from datetime import datetime, time
from typing import Literal

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
    status: str
    latitude: float | None = None
    longitude: float | None = None
    customer_name: str | None = None
    address: str | None = None

    model_config = ConfigDict(from_attributes=True)


def build_route_stop_read(stop, delivery=None) -> RouteStopRead:
    """Build a RouteStopRead from a RouteStop ORM row, enriched with fields
    from the linked Delivery.

    RouteStop itself has no lat/lng/customer_name/address columns (a stop is
    just an ordering + timing record) — that data lives on the Delivery it
    points to, which callers fetch separately and pass in here so the map
    and stop list have something to show without adding a DB
    relationship/join for this alone.
    """
    return RouteStopRead(
        id=stop.id,
        delivery_id=stop.delivery_id,
        sequence=stop.sequence,
        estimated_arrival=stop.estimated_arrival,
        estimated_departure=stop.estimated_departure,
        distance_from_previous_km=stop.distance_from_previous_km,
        status=stop.status,
        latitude=getattr(delivery, "latitude", None),
        longitude=getattr(delivery, "longitude", None),
        customer_name=getattr(delivery, "customer_name", None),
        address=getattr(delivery, "address", None),
    )


class RouteStopStatusUpdate(BaseModel):
    status: Literal["pending", "completed", "skipped"]


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
