"""Route request/response schemas."""

from pydantic import BaseModel


class OptimizeRequest(BaseModel):
    delivery_ids: list[str]
    driver_ids: list[str]
    vehicle_ids: list[str]


class RouteStopRead(BaseModel):
    id: str
    delivery_id: str
    sequence: int


class RouteRead(BaseModel):
    id: str
    driver_id: str | None = None
    status: str
    stops: list[RouteStopRead] = []
