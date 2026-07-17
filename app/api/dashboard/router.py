"""Dashboard API routes: high-level operational overview."""

from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])


@router.get("/overview")
async def get_overview() -> dict:
    """Return summary metrics: active routes, pending deliveries, driver status, etc."""
    raise NotImplementedError
