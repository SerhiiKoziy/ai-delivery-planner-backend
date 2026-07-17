"""Shared FastAPI dependencies: DB session and current-user resolution."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_token
from app.db.models.user import User
from app.db.session import get_session
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.deliveries.service import DeliveryService
from app.services.geocoding.client import GoogleGeocodingClient
from app.services.route_optimizer.service import RouteOptimizerService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session."""
    async for session in get_session():
        yield session


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    """Provide a request-scoped UserRepository bound to the request's DB session."""
    return UserRepository(db)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
) -> User:
    """Resolve the current authenticated user from a bearer JWT."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_token(token)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    if claims.get("type") != "access":
        raise credentials_error

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise credentials_error from exc

    user = await user_repo.get(user_id)
    if user is None:
        raise credentials_error
    return user


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


def get_depot_repository(db: AsyncSession = Depends(get_db)) -> DepotRepository:
    """Provide a request-scoped DepotRepository bound to the request's DB session."""
    return DepotRepository(db)


def get_route_repository(db: AsyncSession = Depends(get_db)) -> RouteRepository:
    """Provide a request-scoped RouteRepository bound to the request's DB session."""
    return RouteRepository(db)


def get_route_stop_repository(db: AsyncSession = Depends(get_db)) -> RouteStopRepository:
    """Provide a request-scoped RouteStopRepository bound to the request's DB session."""
    return RouteStopRepository(db)


def get_route_optimizer_service(
    delivery_repo: DeliveryRepository = Depends(get_delivery_repository),
    vehicle_repo: VehicleRepository = Depends(get_vehicle_repository),
    driver_repo: DriverRepository = Depends(get_driver_repository),
    depot_repo: DepotRepository = Depends(get_depot_repository),
    route_repo: RouteRepository = Depends(get_route_repository),
    route_stop_repo: RouteStopRepository = Depends(get_route_stop_repository),
    db: AsyncSession = Depends(get_db),
) -> RouteOptimizerService:
    """Provide a request-scoped RouteOptimizerService with all its collaborators wired in."""
    return RouteOptimizerService(
        delivery_repo, vehicle_repo, driver_repo, depot_repo, route_repo, route_stop_repo, db
    )
