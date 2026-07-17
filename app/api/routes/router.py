"""Route API routes.

Triggers OR-Tools based multi-driver route optimization and exposes the
resulting routes. The LLM is not involved in optimization — see
services.route_optimizer.
"""

from fastapi import APIRouter

from app.schemas.route import OptimizeRequest, RouteRead

router = APIRouter(tags=["routes"])


@router.post("/optimize", response_model=RouteRead)
async def optimize_routes(payload: OptimizeRequest) -> RouteRead:
    """Run the OR-Tools solver to build optimized multi-driver routes."""
    raise NotImplementedError


@router.get("/{route_id}", response_model=RouteRead)
async def get_route(route_id: str) -> RouteRead:
    """Fetch a previously computed route by id."""
    raise NotImplementedError
