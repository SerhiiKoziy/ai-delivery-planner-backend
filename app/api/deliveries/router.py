"""Delivery API routes.

Covers bulk import (Excel/CSV/manual) and standard CRUD for individual
delivery records. Import parsing/normalization lives in
services.importers, geocoding in services.geocoding, and orchestration in
services.deliveries — this module only wires HTTP.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from app.core.dependencies import get_current_user, get_delivery_service
from app.schemas.delivery import DeliveryCreate, DeliveryImportResult, DeliveryRead, DeliveryUpdate
from app.services.deliveries.service import DeliveryService

router = APIRouter(tags=["deliveries"], dependencies=[Depends(get_current_user)])


@router.post("/import", response_model=DeliveryImportResult)
async def import_deliveries(
    file: UploadFile,
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryImportResult:
    """Import deliveries from an uploaded Excel/CSV file."""
    content = await file.read()
    try:
        return await service.import_file(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/", response_model=DeliveryRead)
async def create_delivery(
    payload: DeliveryCreate,
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryRead:
    """Create a single delivery manually."""
    created = await service.create(payload)
    return DeliveryRead.model_validate(created)


@router.get("/", response_model=list[DeliveryRead])
async def list_deliveries(
    service: DeliveryService = Depends(get_delivery_service),
) -> list[DeliveryRead]:
    """List deliveries for the current organization."""
    deliveries = await service.list_all()
    return [DeliveryRead.model_validate(d) for d in deliveries]


@router.get("/{delivery_id}", response_model=DeliveryRead)
async def get_delivery(
    delivery_id: uuid.UUID,
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryRead:
    """Fetch a single delivery by id."""
    delivery = await service.get(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return DeliveryRead.model_validate(delivery)


@router.put("/{delivery_id}", response_model=DeliveryRead)
async def update_delivery(
    delivery_id: uuid.UUID,
    payload: DeliveryUpdate,
    service: DeliveryService = Depends(get_delivery_service),
) -> DeliveryRead:
    """Update an existing delivery."""
    updated = await service.update(delivery_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return DeliveryRead.model_validate(updated)


@router.delete("/{delivery_id}", status_code=204)
async def delete_delivery(
    delivery_id: uuid.UUID,
    service: DeliveryService = Depends(get_delivery_service),
) -> Response:
    """Delete a delivery."""
    deleted = await service.delete(delivery_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return Response(status_code=204)
