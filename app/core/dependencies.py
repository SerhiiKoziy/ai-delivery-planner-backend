"""Shared FastAPI dependencies: DB session and current-user resolution."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.deliveries.service import DeliveryService
from app.services.geocoding.client import GoogleGeocodingClient

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session."""
    async for session in get_session():
        yield session


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Resolve the current authenticated user from a bearer JWT."""
    raise NotImplementedError


def get_delivery_repository(db: AsyncSession = Depends(get_db)) -> DeliveryRepository:
    """Provide a request-scoped DeliveryRepository bound to the request's DB session."""
    return DeliveryRepository(db)


def get_delivery_service(
    repo: DeliveryRepository = Depends(get_delivery_repository),
) -> DeliveryService:
    """Provide a request-scoped DeliveryService."""
    return DeliveryService(repo, GoogleGeocodingClient())


def get_driver_repository(db: AsyncSession = Depends(get_db)) -> DriverRepository:
    """Provide a request-scoped DriverRepository bound to the request's DB session."""
    return DriverRepository(db)


def get_vehicle_repository(db: AsyncSession = Depends(get_db)) -> VehicleRepository:
    """Provide a request-scoped VehicleRepository bound to the request's DB session."""
    return VehicleRepository(db)
