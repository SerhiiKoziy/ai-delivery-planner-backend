"""Shared FastAPI dependencies: DB session and current-user resolution."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.plans import PLAN_AI_CALL_LIMITS, PLAN_ROUTE_LIMITS
from app.core.security import InvalidTokenError, decode_token
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_session
from app.repositories.chat_message_repository import ChatMessageRepository
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.ai import DeliveryAnalysisResult
from app.schemas.delivery import DeliveryImportRow, DeliveryRead
from app.schemas.route import RouteRead, build_route_stop_read
from app.services.ai.chat import handle_chat_message
from app.services.ai.client import get_openai_client
from app.services.ai.explainer import explain_route
from app.services.ai.planner import analyze_delivery_list
from app.services.dashboard.service import DashboardService
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


def get_organization_repository(db: AsyncSession = Depends(get_db)) -> OrganizationRepository:
    """Provide a request-scoped OrganizationRepository bound to the request's DB session."""
    return OrganizationRepository(db)


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


async def get_current_organization(
    current_user: User = Depends(get_current_user),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> Organization:
    """Resolve the caller's Organization row (plan, usage counters)."""
    organization = await org_repo.get(current_user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def get_delivery_repository(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeliveryRepository:
    """Provide a request-scoped DeliveryRepository, scoped to the caller's organization."""
    return DeliveryRepository(db, current_user.organization_id)


def get_delivery_service(
    repo: DeliveryRepository = Depends(get_delivery_repository),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
    organization: Organization = Depends(get_current_organization),
) -> DeliveryService:
    """Provide a request-scoped DeliveryService, quota-guarded per organization."""
    return DeliveryService(repo, GoogleGeocodingClient(), org_repo, organization)


def get_driver_repository(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DriverRepository:
    """Provide a request-scoped DriverRepository, scoped to the caller's organization."""
    return DriverRepository(db, current_user.organization_id)


def get_vehicle_repository(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VehicleRepository:
    """Provide a request-scoped VehicleRepository, scoped to the caller's organization."""
    return VehicleRepository(db, current_user.organization_id)


def get_depot_repository(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DepotRepository:
    """Provide a request-scoped DepotRepository, scoped to the caller's organization."""
    return DepotRepository(db, current_user.organization_id)


def get_route_repository(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RouteRepository:
    """Provide a request-scoped RouteRepository, scoped to the caller's organization."""
    return RouteRepository(db, current_user.organization_id)


def get_route_stop_repository(db: AsyncSession = Depends(get_db)) -> RouteStopRepository:
    """Provide a request-scoped RouteStopRepository bound to the request's DB session."""
    return RouteStopRepository(db)


def get_chat_message_repository(db: AsyncSession = Depends(get_db)) -> ChatMessageRepository:
    """Provide a request-scoped ChatMessageRepository bound to the request's DB session."""
    return ChatMessageRepository(db)


async def require_route_quota(
    organization: Organization = Depends(get_current_organization),
) -> Organization:
    """Reject route generation once the caller's organization has hit its
    plan's lifetime route quota (e.g. 5 for TRIAL). Unlimited plans
    (`PLAN_ROUTE_LIMITS[plan] is None`) always pass through.

    Returns the organization so the caller can increment its counter after a
    successful generation without a second fetch.
    """
    limit = PLAN_ROUTE_LIMITS.get(organization.subscription_plan)
    if limit is not None and organization.routes_generated_count >= limit:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Route generation limit reached for the "
                f"'{organization.subscription_plan.value}' plan ({limit} routes). "
                "Upgrade your plan to generate more routes."
            ),
        )
    return organization


async def require_ai_quota(
    organization: Organization = Depends(get_current_organization),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> None:
    """Consume one unit of the caller's lifetime AI-call quota (e.g. 20 for
    TRIAL) before an OpenAI-backed endpoint runs — checked and consumed
    atomically up front, so a request that's rejected never reaches OpenAI.

    Counts per HTTP call, not per underlying OpenAI request (e.g. /replan's
    up-to-2 internal calls still cost 1 unit), matching how route generation
    is counted per POST /optimize call rather than per solver invocation.
    """
    limit = PLAN_AI_CALL_LIMITS.get(organization.subscription_plan)
    allowed = await org_repo.try_consume_quota(
        organization.id, counter_column="ai_calls_count", limit=limit
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"AI usage limit reached for the '{organization.subscription_plan.value}' plan "
                f"({limit} calls). Upgrade your plan to continue using AI features."
            ),
        )


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


def get_dashboard_service(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardService:
    """Provide a request-scoped DashboardService, scoped to the caller's organization."""
    return DashboardService(db, current_user.organization_id)


def get_ai_model() -> str:
    """Return the configured OpenAI model name for the AI services (overridable in tests)."""
    return get_settings().OPENAI_MODEL


class DeliveryAnalysisService:
    """Binds an OpenAI client/model to `analyze_delivery_list` for DI."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    async def run(self, rows: list[DeliveryImportRow]) -> DeliveryAnalysisResult:
        return await analyze_delivery_list(rows, client=self.client, model=self.model)


class RouteExplainerService:
    """Binds an OpenAI client/model to `explain_route` for DI."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    async def run(self, route: RouteRead, deliveries: list[DeliveryRead]) -> str:
        return await explain_route(route, deliveries, client=self.client, model=self.model)


class RouteChatService:
    """Binds an OpenAI client/model to `handle_chat_message` for DI."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    async def run(
        self,
        message: str,
        route: RouteRead,
        deliveries: list[DeliveryRead],
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        return await handle_chat_message(
            message, route, deliveries, history, client=self.client, model=self.model
        )


def get_delivery_analysis_service(
    client: AsyncOpenAI = Depends(get_openai_client),
    model: str = Depends(get_ai_model),
) -> DeliveryAnalysisService:
    """Provide a request-scoped DeliveryAnalysisService with client/model bound."""
    return DeliveryAnalysisService(client, model)


def get_route_explainer_service(
    client: AsyncOpenAI = Depends(get_openai_client),
    model: str = Depends(get_ai_model),
) -> RouteExplainerService:
    """Provide a request-scoped RouteExplainerService with client/model bound."""
    return RouteExplainerService(client, model)


def get_route_chat_service(
    client: AsyncOpenAI = Depends(get_openai_client),
    model: str = Depends(get_ai_model),
) -> RouteChatService:
    """Provide a request-scoped RouteChatService with client/model bound."""
    return RouteChatService(client, model)


async def get_route_context(
    route_id: uuid.UUID,
    route_repo: RouteRepository = Depends(get_route_repository),
    route_stop_repo: RouteStopRepository = Depends(get_route_stop_repository),
    delivery_repo: DeliveryRepository = Depends(get_delivery_repository),
) -> tuple[RouteRead, list[DeliveryRead]]:
    """Fetch a Route with its stops and linked deliveries, assembled for AI context.

    Raises 404 if the route doesn't exist.
    """
    route = await route_repo.get(route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    stops = await route_stop_repo.list_by_route(route_id)
    delivery_ids = [stop.delivery_id for stop in stops]
    deliveries = await delivery_repo.get_many(delivery_ids) if delivery_ids else []
    deliveries_by_id = {d.id: d for d in deliveries}

    route_read = RouteRead(
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
        stops=[build_route_stop_read(stop, deliveries_by_id.get(stop.delivery_id)) for stop in stops],
    )
    delivery_reads = [DeliveryRead.model_validate(d) for d in deliveries]
    return route_read, delivery_reads
