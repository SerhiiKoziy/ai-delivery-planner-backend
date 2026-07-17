"""Driver request/response schemas."""

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict


class DriverCreate(BaseModel):
    name: str
    phone: str
    status: str = "active"
    working_hours_start: time = time(8, 0)
    working_hours_end: time = time(18, 0)
    break_start: time | None = time(13, 0)
    break_end: time | None = time(14, 0)
    max_working_minutes: int = 600


class DriverUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    status: str | None = None
    working_hours_start: time | None = None
    working_hours_end: time | None = None
    break_start: time | None = None
    break_end: time | None = None
    max_working_minutes: int | None = None


class DriverRead(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    status: str
    working_hours_start: time
    working_hours_end: time
    break_start: time | None = None
    break_end: time | None = None
    max_working_minutes: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
