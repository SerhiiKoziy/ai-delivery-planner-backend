"""Shared pytest fixtures: an in-memory SQLite async DB and a test client
wired to it via FastAPI dependency overrides.

Every non-auth router now requires `get_current_user`. The `client` fixture
therefore also overrides that dependency so existing endpoint tests keep
exercising business logic without each one having to mint a real JWT; the
auth flow itself (register/login/refresh) and the "no token" 401 behavior
are covered separately using a real token / the unauthenticated app.
"""

import json
from datetime import UTC, datetime, time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.dependencies import get_ai_model, get_current_user, get_db
from app.core.rate_limiting import login_rate_limiter, register_rate_limiter
from app.core.security import hash_password
from app.db.models.base import Base
from app.db.models.delivery import DeliveryPriority
from app.db.models.organization import Organization
from app.db.models.user import User
from app.main import app
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.user_repository import UserRepository
from app.services.ai.client import get_openai_client

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True, scope="session")
def _disable_real_email_sending():
    """Tests must never hit real Gmail SMTP, regardless of what's in the
    local .env — force the no-provider (log-only) path for the whole run."""
    get_settings().GMAIL_ADDRESS = ""
    get_settings().GMAIL_APP_PASSWORD = ""


@pytest_asyncio.fixture
async def db_session():
    """Create all tables, yield a session, then drop all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def test_organization(db_session: AsyncSession) -> Organization:
    """Persist and return the organization `test_user` belongs to."""
    now = datetime.now(UTC)
    return await OrganizationRepository(db_session).create(
        name="Test Organization", created_at=now, updated_at=now
    )


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_organization: Organization) -> User:
    """Persist and return a real user row to authenticate test requests as."""
    now = datetime.now(UTC)
    return await UserRepository(db_session).create(
        email="test.user@example.com",
        hashed_password=hash_password("test-password-123"),
        organization_id=test_organization.id,
        created_at=now,
        updated_at=now,
    )


@pytest_asyncio.fixture
async def other_organization(db_session: AsyncSession) -> Organization:
    """A second organization, distinct from `test_organization`, for tenant-isolation tests."""
    now = datetime.now(UTC)
    return await OrganizationRepository(db_session).create(
        name="Other Organization", created_at=now, updated_at=now
    )


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession, other_organization: Organization) -> User:
    """A user belonging to `other_organization`, distinct from `test_user`."""
    now = datetime.now(UTC)
    return await UserRepository(db_session).create(
        email="other.user@example.com",
        hashed_password=hash_password("other-password-123"),
        organization_id=other_organization.id,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def client(db_session, test_user: User) -> TestClient:
    """Return a FastAPI TestClient authenticated as `test_user`.

    Overrides `get_db` to use the in-memory test session and `get_current_user`
    to resolve directly to `test_user`, so callers don't need to manage a real
    JWT for endpoint tests that only care about business logic.
    """

    async def _override_get_db():
        yield db_session

    async def _override_get_current_user() -> User:
        return test_user

    async def _no_op() -> None:
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    # Register/login rate limiting is tested in isolation (test_rate_limiting.py)
    # against its own raw client — overridden here so unrelated tests calling
    # /auth/register or /auth/login a handful of times don't trip a shared,
    # process-lifetime in-memory window.
    app.dependency_overrides[register_rate_limiter] = _no_op
    app.dependency_overrides[login_rate_limiter] = _no_op
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(register_rate_limiter, None)
        app.dependency_overrides.pop(login_rate_limiter, None)


@pytest.fixture
def unauthenticated_client(db_session) -> TestClient:
    """Return a TestClient with only `get_db` overridden (no auth override).

    Used to verify that protected endpoints correctly reject requests with
    no/invalid bearer token, and to exercise the real register/login/refresh
    flow end-to-end.
    """

    async def _override_get_db():
        yield db_session

    async def _no_op() -> None:
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[register_rate_limiter] = _no_op
    app.dependency_overrides[login_rate_limiter] = _no_op
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(register_rate_limiter, None)
        app.dependency_overrides.pop(login_rate_limiter, None)


# ---------------------------------------------------------------------------
# AI service fixtures: a fake AsyncOpenAI-shaped client so app.services.ai
# tests/endpoints never touch the network. Structured (json_schema) calls are
# answered by inspecting the actual outgoing payload, so fixtures aren't tied
# to a specific number/order of rows; plain (non-structured) chat calls used
# by explain/chat return a canned reply string.
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


def _fake_address_cleaning(payload: dict) -> dict:
    return {
        "addresses": [
            {
                "index": item["index"],
                "normalized": item["address"].strip(),
                "city": None,
                "postal_code": None,
                "confidence": 0.9,
                "corrections": [],
            }
            for item in payload["addresses"]
        ]
    }


def _fake_note_parsing(payload: dict) -> dict:
    notes = []
    for item in payload["notes"]:
        text = item["text"]
        text_lower = text.lower()
        notes.append(
            {
                "index": item["index"],
                "call_before": "call" in text_lower,
                "call_before_minutes": None,
                "gate_code": "3456" if "3456" in text else None,
                "earliest_time": "16:00" if "16:00" in text else None,
                "has_dog": "dog" in text_lower,
                "other_instructions": [],
            }
        )
    return {"notes": notes}


def _fake_duplicate_detection(payload: dict) -> dict:
    row_numbers_by_name: dict[str, list[int]] = {}
    for row in payload["rows"]:
        key = row["customer_name"].strip().lower()
        row_numbers_by_name.setdefault(key, []).append(row["row_number"])
    groups = [
        {
            "row_indices": row_numbers,
            "customer_name": key,
            "reason": "Same customer name appears on multiple rows",
        }
        for key, row_numbers in row_numbers_by_name.items()
        if len(row_numbers) >= 2
    ]
    return {"groups": groups}


_DEFAULT_REPLAN_INTERPRETATION = {
    "event_type": "unrecognized",
    "affected_stop_sequence": None,
    "new_window_start": None,
    "new_window_end": None,
    "delay_minutes": None,
    "summary": "Default fake interpretation: no test override was set.",
}


class FakeOpenAIClient:
    """Fake AsyncOpenAI-shaped client standing in for `get_openai_client`."""

    def __init__(self, plain_reply: str = "This is a canned AI reply.") -> None:
        self.plain_reply = plain_reply
        # Tests set this directly (mirroring `plain_reply`) to control what the
        # fake "interprets" a dispatcher message as, since the fake can't
        # actually understand free text the way a real model would.
        self.replan_interpretation: dict = dict(_DEFAULT_REPLAN_INTERPRETATION)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model, messages, response_format=None, **kwargs):
        self.calls.append({"model": model, "messages": messages, "response_format": response_format})

        if response_format is None:
            return _FakeCompletion(self.plain_reply)

        schema_name = response_format["json_schema"]["name"]
        payload = json.loads(messages[-1]["content"])
        if schema_name == "cleaned_addresses":
            result = _fake_address_cleaning(payload)
        elif schema_name == "parsed_delivery_notes":
            result = _fake_note_parsing(payload)
        elif schema_name == "duplicate_groups":
            result = _fake_duplicate_detection(payload)
        elif schema_name == "replan_interpretation":
            result = self.replan_interpretation
        else:  # pragma: no cover - defensive, unknown schema
            result = {}
        return _FakeCompletion(json.dumps(result))


@pytest.fixture
def mock_openai_client() -> FakeOpenAIClient:
    """A fresh fake OpenAI client instance, network-free and call-recording."""
    return FakeOpenAIClient()


@pytest.fixture
def ai_client(client: TestClient, mock_openai_client: FakeOpenAIClient) -> TestClient:
    """Extend `client` with the OpenAI dependency overridden by a fake client."""

    def _override_get_openai_client() -> FakeOpenAIClient:
        return mock_openai_client

    def _override_get_ai_model() -> str:
        return "gpt-4.1-mini-test"

    app.dependency_overrides[get_openai_client] = _override_get_openai_client
    app.dependency_overrides[get_ai_model] = _override_get_ai_model
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_openai_client, None)
        app.dependency_overrides.pop(get_ai_model, None)


@pytest_asyncio.fixture
async def route_with_stops(db_session: AsyncSession, test_organization: Organization) -> dict:
    """Persist a minimal Depot + Delivery + Route + RouteStop, owned by
    `test_organization`, for AI route-context tests."""
    org_id = test_organization.id
    depot = await DepotRepository(db_session, org_id).create(
        address="Kyiv depot", latitude=50.4501, longitude=30.5234
    )
    delivery = await DeliveryRepository(db_session, org_id).create(
        customer_name="Acme LLC",
        address="Kyiv, Khreshchatyk 1",
        priority=DeliveryPriority.HIGH,
        unloading_minutes=10,
        weight_kg=5.0,
        volume_m3=0.2,
        delivery_window_start=time(10, 0),
        delivery_window_end=time(12, 0),
        notes="Please call before delivery.",
        status="geocoded",
        latitude=50.46,
        longitude=30.53,
    )
    route = await RouteRepository(db_session, org_id).create(
        depot_id=depot.id,
        status="planned",
        return_to_depot=True,
        total_distance_km=12.5,
        total_duration_minutes=45,
    )
    stop = await RouteStopRepository(db_session).create(
        route_id=route.id,
        delivery_id=delivery.id,
        sequence=0,
        estimated_arrival=time(9, 30),
        estimated_departure=time(9, 40),
        distance_from_previous_km=12.5,
    )
    return {
        "depot_id": depot.id,
        "delivery_id": delivery.id,
        "route_id": route.id,
        "stop_id": stop.id,
    }
