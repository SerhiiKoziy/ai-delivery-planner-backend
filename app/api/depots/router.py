"""Depot API routes: list, create, read, update, delete depots.

No business logic beyond persistence lives here — the router talks
directly to the DepotRepository via dependency injection.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.dependencies import (
    get_current_organization,
    get_current_user,
    get_depot_repository,
    get_organization_repository,
)
from app.core.plans import PLAN_GEOCODE_LIMITS
from app.db.models.organization import Organization
from app.repositories.depot_repository import DepotRepository
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.depot import DepotCreate, DepotGeocodeRequest, DepotGeocodeResult, DepotRead, DepotUpdate
from app.services.geocoding.client import GoogleGeocodingClient

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


@router.post("/geocode", response_model=DepotGeocodeResult)
async def geocode_depot_address(
    payload: DepotGeocodeRequest,
    organization: Organization = Depends(get_current_organization),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> DepotGeocodeResult:
    """Resolve a free-text address to coordinates, for the "find location"
    step in the depot-creation form (the frontend then lets the user confirm
    before actually creating the depot with the resolved coordinates).

    Counts against the same `geocode_calls_count` plan quota as delivery
    geocoding — it's the same paid Google API call, so it must be gated the
    same way or it becomes an unmetered way to spam that API.
    """
    limit = PLAN_GEOCODE_LIMITS.get(organization.subscription_plan)
    allowed = await org_repo.try_consume_quota(
        organization.id, counter_column="geocode_calls_count", limit=limit
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Geocoding limit reached for the '{organization.subscription_plan.value}' plan "
                f"({limit} addresses). Upgrade your plan to geocode more addresses."
            ),
        )

    result = await GoogleGeocodingClient().geocode_full(payload.address)
    if result is None:
        raise HTTPException(status_code=404, detail="Could not find that address")

    return DepotGeocodeResult(
        latitude=result.latitude,
        longitude=result.longitude,
        formatted_address=result.formatted_address,
    )


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
