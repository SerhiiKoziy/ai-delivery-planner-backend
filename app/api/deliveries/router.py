"""Delivery API routes.

Covers bulk import (Excel/CSV/manual) and standard CRUD for individual
delivery records. Import parsing/LLM cleanup lives in services.importers
and services.ai — this module only wires HTTP.
"""

from fastapi import APIRouter, UploadFile

from app.schemas.delivery import DeliveryCreate, DeliveryRead

router = APIRouter(tags=["deliveries"])


@router.post("/import", response_model=list[DeliveryRead])
async def import_deliveries(file: UploadFile) -> list[DeliveryRead]:
    """Import deliveries from an uploaded Excel/CSV file."""
    raise NotImplementedError


@router.post("/", response_model=DeliveryRead)
async def create_delivery(payload: DeliveryCreate) -> DeliveryRead:
    """Create a single delivery manually."""
    raise NotImplementedError


@router.get("/", response_model=list[DeliveryRead])
async def list_deliveries() -> list[DeliveryRead]:
    """List deliveries for the current organization."""
    raise NotImplementedError


@router.put("/{delivery_id}", response_model=DeliveryRead)
async def update_delivery(delivery_id: str, payload: DeliveryCreate) -> DeliveryRead:
    """Update an existing delivery."""
    raise NotImplementedError


@router.delete("/{delivery_id}")
async def delete_delivery(delivery_id: str) -> None:
    """Delete a delivery."""
    raise NotImplementedError
