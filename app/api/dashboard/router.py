"""Dashboard API routes: high-level operational overview."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/overview")
async def get_overview() -> dict:
    """Return summary metrics: active routes, pending deliveries, driver status, etc."""
    raise NotImplementedError
