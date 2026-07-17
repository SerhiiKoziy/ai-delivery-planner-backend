"""Driver request/response schemas."""

from pydantic import BaseModel


class DriverCreate(BaseModel):
    name: str
    phone: str


class DriverRead(BaseModel):
    id: str
    name: str
    phone: str
