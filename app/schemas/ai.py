"""AI request/response schemas: delivery-list analysis and route Q&A."""

import uuid
from datetime import time
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class AddressCleaningResult(BaseModel):
    original: str
    normalized: str
    city: str | None = None
    postal_code: str | None = None
    confidence: float
    corrections: list[str] = []


class ParsedDeliveryNote(BaseModel):
    call_before: bool = False
    call_before_minutes: int | None = None
    gate_code: str | None = None
    earliest_time: str | None = None  # "HH:MM" 24h format, or None
    has_dog: bool = False
    other_instructions: list[str] = []


class DuplicateGroup(BaseModel):
    row_indices: list[int]
    customer_name: str
    reason: str


class DeliveryRowAnalysis(BaseModel):
    row_number: int
    address: AddressCleaningResult
    parsed_note: ParsedDeliveryNote | None = None


class DeliveryAnalysisResult(BaseModel):
    total_rows: int
    rows: list[DeliveryRowAnalysis]
    duplicate_groups: list[DuplicateGroup] = []


class ChatRequest(BaseModel):
    message: str
    route_id: uuid.UUID


class ChatResponse(BaseModel):
    reply: str


class ExplainRequest(BaseModel):
    route_id: uuid.UUID


class ExplainResponse(BaseModel):
    explanation: str


class ReplanEventType(str, Enum):
    CUSTOMER_UNREACHABLE = "customer_unreachable"
    DELIVERY_CANCELLED = "delivery_cancelled"
    DELIVERY_RESCHEDULED = "delivery_rescheduled"
    DRIVER_DELAYED = "driver_delayed"
    UNRECOGNIZED = "unrecognized"


class ReplanInterpretation(BaseModel):
    event_type: ReplanEventType
    affected_stop_sequence: int | None = None
    new_window_start: str | None = None  # "HH:MM", only for DELIVERY_RESCHEDULED
    new_window_end: str | None = None
    delay_minutes: int | None = None  # only for DRIVER_DELAYED
    summary: str


class StopDiffEntry(BaseModel):
    delivery_id: uuid.UUID
    customer_name: str
    change: Literal["unchanged", "reordered", "time_shifted", "removed", "window_updated"]
    old_sequence: int | None = None
    new_sequence: int | None = None
    old_estimated_arrival: time | None = None
    new_estimated_arrival: time | None = None
    reason: str | None = None


class ReplanRequest(BaseModel):
    route_id: uuid.UUID
    message: str
    dry_run: bool = False


class ReplanResult(BaseModel):
    route_id: uuid.UUID
    interpretation: ReplanInterpretation
    applied: bool
    diff: list[StopDiffEntry]
    total_distance_km_before: float
    total_distance_km_after: float
    total_duration_minutes_before: int
    total_duration_minutes_after: int
    time_saved_minutes: float
    explanation: str
