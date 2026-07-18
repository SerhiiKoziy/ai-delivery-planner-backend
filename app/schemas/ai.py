"""AI request/response schemas: delivery-list analysis and route Q&A."""

import uuid

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
