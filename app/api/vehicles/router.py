"""Vehicle API routes: list, create, update vehicles."""

from fastapi import APIRouter

from app.schemas.vehicle import VehicleCreate, VehicleRead

router = APIRouter(tags=["vehicles"])


@router.get("/", response_model=list[VehicleRead])
async def list_vehicles() -> list[VehicleRead]:
    """List vehicles for the current organization."""
    raise NotImplementedError


@router.post("/", response_model=VehicleRead)
async def create_vehicle(payload: VehicleCreate) -> VehicleRead:
    """Register a new vehicle."""
    raise NotImplementedError


@router.put("/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle(vehicle_id: str, payload: VehicleCreate) -> VehicleRead:
    """Update an existing vehicle, e.g. capacity."""
    raise NotImplementedError
