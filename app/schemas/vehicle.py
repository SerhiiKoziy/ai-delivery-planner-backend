"""Vehicle request/response schemas."""

from pydantic import BaseModel


class VehicleCreate(BaseModel):
    license_plate: str
    capacity: int


class VehicleRead(BaseModel):
    id: str
    license_plate: str
    capacity: int
