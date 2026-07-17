"""Driver API routes: list, create, update drivers."""

from fastapi import APIRouter

from app.schemas.driver import DriverCreate, DriverRead

router = APIRouter(tags=["drivers"])


@router.get("/", response_model=list[DriverRead])
async def list_drivers() -> list[DriverRead]:
    """List drivers for the current organization."""
    raise NotImplementedError


@router.post("/", response_model=DriverRead)
async def create_driver(payload: DriverCreate) -> DriverRead:
    """Register a new driver."""
    raise NotImplementedError


@router.put("/{driver_id}", response_model=DriverRead)
async def update_driver(driver_id: str, payload: DriverCreate) -> DriverRead:
    """Update an existing driver, e.g. working hours."""
    raise NotImplementedError
