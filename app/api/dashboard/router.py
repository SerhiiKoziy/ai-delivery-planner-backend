"""Dashboard API routes: high-level operational overview."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user, get_dashboard_service
from app.schemas.dashboard import DashboardOverview
from app.services.dashboard.service import DashboardService

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardOverview:
    """Return summary metrics: deliveries today, active drivers, distance, late deliveries."""
    return await service.get_overview()
