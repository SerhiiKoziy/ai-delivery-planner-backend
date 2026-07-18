"""Depot API routes: list, create, read, update, delete depots.

No business logic beyond persistence lives here — the router talks
directly to the DepotRepository via dependency injection.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.dependencies import get_current_user, get_depot_repository
from app.repositories.depot_repository import DepotRepository
from app.schemas.depot import DepotCreate, DepotRead, DepotUpdate

router = APIRouter(tags=["depots"], dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[DepotRead])
async def list_depots(
    repo: DepotRepository = Depends(get_depot_repository),
) -> list[DepotRead]:
    """List depots for the current organization."""
    depots = await repo.list()
    return [DepotRead.model_validate(d) for d in depots]


@router.post("/", response_model=DepotRead)
async def create_depot(
    payload: DepotCreate,
    repo: DepotRepository = Depends(get_depot_repository),
) -> DepotRead:
    """Register a new depot."""
    created = await repo.create(**payload.model_dump())
    return DepotRead.model_validate(created)


@router.get("/{depot_id}", response_model=DepotRead)
async def get_depot(
    depot_id: uuid.UUID,
    repo: DepotRepository = Depends(get_depot_repository),
) -> DepotRead:
    """Fetch a single depot by id."""
    depot = await repo.get(depot_id)
    if depot is None:
        raise HTTPException(status_code=404, detail="Depot not found")
    return DepotRead.model_validate(depot)


@router.put("/{depot_id}", response_model=DepotRead)
async def update_depot(
    depot_id: uuid.UUID,
    payload: DepotUpdate,
    repo: DepotRepository = Depends(get_depot_repository),
) -> DepotRead:
    """Update an existing depot."""
    updated = await repo.update(depot_id, **payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Depot not found")
    return DepotRead.model_validate(updated)


@router.delete("/{depot_id}", status_code=204)
async def delete_depot(
    depot_id: uuid.UUID,
    repo: DepotRepository = Depends(get_depot_repository),
) -> Response:
    """Delete a depot."""
    deleted = await repo.delete(depot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Depot not found")
    return Response(status_code=204)
