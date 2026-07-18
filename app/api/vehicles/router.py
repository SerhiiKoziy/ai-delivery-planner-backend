"""Vehicle API routes: list, create, read, update, delete vehicles.

No business logic beyond persistence lives here — the router talks
directly to the VehicleRepository via dependency injection. A `driver_id`
is validated to belong to the caller's own organization (via the
org-scoped DriverRepository), since a bare DB foreign key wouldn't stop a
vehicle from being linked to another organization's driver.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.dependencies import get_current_user, get_driver_repository, get_vehicle_repository
from app.repositories.driver_repository import DriverRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate

router = APIRouter(tags=["vehicles"], dependencies=[Depends(get_current_user)])


async def _check_driver_in_org(driver_id: uuid.UUID | None, driver_repo: DriverRepository) -> None:
    if driver_id is not None and await driver_repo.get(driver_id) is None:
        raise HTTPException(status_code=422, detail="Driver not found")


@router.get("/", response_model=list[VehicleRead])
async def list_vehicles(
    repo: VehicleRepository = Depends(get_vehicle_repository),
) -> list[VehicleRead]:
    """List vehicles for the current organization."""
    vehicles = await repo.list()
    return [VehicleRead.model_validate(v) for v in vehicles]


@router.post("/", response_model=VehicleRead)
async def create_vehicle(
    payload: VehicleCreate,
    repo: VehicleRepository = Depends(get_vehicle_repository),
    driver_repo: DriverRepository = Depends(get_driver_repository),
) -> VehicleRead:
    """Register a new vehicle."""
    await _check_driver_in_org(payload.driver_id, driver_repo)
    created = await repo.create(**payload.model_dump())
    return VehicleRead.model_validate(created)


@router.get("/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    repo: VehicleRepository = Depends(get_vehicle_repository),
) -> VehicleRead:
    """Fetch a single vehicle by id."""
    vehicle = await repo.get(vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return VehicleRead.model_validate(vehicle)


@router.put("/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    repo: VehicleRepository = Depends(get_vehicle_repository),
    driver_repo: DriverRepository = Depends(get_driver_repository),
) -> VehicleRead:
    """Update an existing vehicle, e.g. capacity."""
    update_fields = payload.model_dump(exclude_unset=True)
    if "driver_id" in update_fields:
        await _check_driver_in_org(update_fields["driver_id"], driver_repo)
    updated = await repo.update(vehicle_id, **update_fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return VehicleRead.model_validate(updated)


@router.delete("/{vehicle_id}", status_code=204)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    repo: VehicleRepository = Depends(get_vehicle_repository),
) -> Response:
    """Delete a vehicle."""
    deleted = await repo.delete(vehicle_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return Response(status_code=204)
