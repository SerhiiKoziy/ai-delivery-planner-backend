"""Driver API routes: list, create, read, update, delete drivers.

No business logic beyond persistence lives here — the router talks
directly to the DriverRepository via dependency injection.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.dependencies import get_driver_repository
from app.repositories.driver_repository import DriverRepository
from app.schemas.driver import DriverCreate, DriverRead, DriverUpdate

router = APIRouter(tags=["drivers"])


@router.get("/", response_model=list[DriverRead])
async def list_drivers(
    repo: DriverRepository = Depends(get_driver_repository),
) -> list[DriverRead]:
    """List drivers for the current organization."""
    drivers = await repo.list()
    return [DriverRead.model_validate(d) for d in drivers]


@router.post("/", response_model=DriverRead)
async def create_driver(
    payload: DriverCreate,
    repo: DriverRepository = Depends(get_driver_repository),
) -> DriverRead:
    """Register a new driver."""
    created = await repo.create(**payload.model_dump())
    return DriverRead.model_validate(created)


@router.get("/{driver_id}", response_model=DriverRead)
async def get_driver(
    driver_id: uuid.UUID,
    repo: DriverRepository = Depends(get_driver_repository),
) -> DriverRead:
    """Fetch a single driver by id."""
    driver = await repo.get(driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    return DriverRead.model_validate(driver)


@router.put("/{driver_id}", response_model=DriverRead)
async def update_driver(
    driver_id: uuid.UUID,
    payload: DriverUpdate,
    repo: DriverRepository = Depends(get_driver_repository),
) -> DriverRead:
    """Update an existing driver, e.g. working hours."""
    updated = await repo.update(driver_id, **payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    return DriverRead.model_validate(updated)


@router.delete("/{driver_id}", status_code=204)
async def delete_driver(
    driver_id: uuid.UUID,
    repo: DriverRepository = Depends(get_driver_repository),
) -> Response:
    """Delete a driver."""
    deleted = await repo.delete(driver_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Driver not found")
    return Response(status_code=204)
