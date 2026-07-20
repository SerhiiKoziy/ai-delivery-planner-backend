"""Dashboard API routes: high-level operational overview and usage history."""

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user, get_dashboard_service
from app.schemas.dashboard import DashboardOverview, DashboardUsageHistory
from app.services.dashboard.service import DashboardService

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardOverview:
    """Return summary metrics: deliveries today, active drivers/vehicles,
    distance, late deliveries."""
    return await service.get_overview()


@router.get("/usage-history", response_model=DashboardUsageHistory)
async def get_usage_history(
    days: int = Query(default=30, ge=1, le=90),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardUsageHistory:
    """Return a zero-filled, day-bucketed usage series for the last `days` days."""
    return await service.get_usage_history(days=days)
