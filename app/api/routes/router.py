"""Route API routes.

Triggers OR-Tools based multi-driver route optimization and exposes the
resulting routes. The LLM is not involved in optimization — see
services.route_optimizer.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (
    get_current_user,
    get_organization_repository,
    get_route_optimizer_service,
    get_route_repository,
    get_route_stop_repository,
    require_route_quota,
)
from app.db.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.schemas.route import (
    OptimizeRequest,
    OptimizeResult,
    RouteRead,
    RouteStopRead,
    RouteStopStatusUpdate,
    build_route_stop_read,
)
from app.services.route_optimizer.service import RouteOptimizerService

router = APIRouter(tags=["routes"], dependencies=[Depends(get_current_user)])


@router.post("/optimize", response_model=OptimizeResult)
async def optimize_routes(
    payload: OptimizeRequest,
    organization: Organization = Depends(require_route_quota),
    service: RouteOptimizerService = Depends(get_route_optimizer_service),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> OptimizeResult:
    """Run the OR-Tools solver to build optimized multi-driver routes.

    `require_route_quota` blocks the call up front once the org's plan quota
    is exhausted; each route actually created below then counts against it,
    so a single multi-driver call may push the count slightly past the limit
    rather than only ever landing exactly on it.
    """
    try:
        result = await service.optimize(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.routes:
        await org_repo.increment_route_count(organization.id, by=len(result.routes))

    return result


@router.get("/{route_id}", response_model=RouteRead)
async def get_route(
    route_id: uuid.UUID,
    service: RouteOptimizerService = Depends(get_route_optimizer_service),
) -> RouteRead:
    """Fetch a previously computed route by id, including its stops."""
    result = await service.get_route_with_stops(route_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Route not found")
    route, stops, deliveries_by_id = result
    return RouteRead(
        id=route.id,
        driver_id=route.driver_id,
        vehicle_id=route.vehicle_id,
        depot_id=route.depot_id,
        status=route.status,
        return_to_depot=route.return_to_depot,
        total_distance_km=route.total_distance_km,
        total_duration_minutes=route.total_duration_minutes,
        created_at=route.created_at,
        updated_at=route.updated_at,
        stops=[build_route_stop_read(s, deliveries_by_id.get(s.delivery_id)) for s in stops],
    )


@router.patch("/{route_id}/stops/{stop_id}", response_model=RouteStopRead)
async def update_stop_status(
    route_id: uuid.UUID,
    stop_id: uuid.UUID,
    payload: RouteStopStatusUpdate,
    route_repository: RouteRepository = Depends(get_route_repository),
    route_stop_repository: RouteStopRepository = Depends(get_route_stop_repository),
) -> RouteStopRead:
    """Mark a route stop as pending/completed/skipped.

    RouteStop has no organization_id of its own — ownership is enforced by
    requiring the route itself to resolve under the caller's organization
    before the stop is looked up.
    """
    if await route_repository.get(route_id) is None:
        raise HTTPException(status_code=404, detail="Route not found")

    stop = await route_stop_repository.get(stop_id)
    if stop is None or stop.route_id != route_id:
        raise HTTPException(status_code=404, detail="Route stop not found")

    updated = await route_stop_repository.update(stop_id, status=payload.status)
    return RouteStopRead.model_validate(updated)
