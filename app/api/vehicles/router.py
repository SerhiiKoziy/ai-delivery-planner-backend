"""Vehicle API routes: list, create, read, update, delete vehicles.

No business logic beyond persistence lives here — the router talks
directly to the VehicleRepository via dependency injection. Note that an
invalid `driver_id` is not validated against the drivers table here; it
will simply fail at the DB foreign-key level.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.dependencies import get_current_user, get_vehicle_repository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate

router = APIRouter(tags=["vehicles"], dependencies=[Depends(get_current_user)])


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
) -> VehicleRead:
    """Register a new vehicle."""
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
) -> VehicleRead:
    """Update an existing vehicle, e.g. capacity."""
    updated = await repo.update(vehicle_id, **payload.model_dump(exclude_unset=True))
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
