"""Shared pytest fixtures: an in-memory SQLite async DB and a test client
wired to it via FastAPI dependency overrides.

Every non-auth router now requires `get_current_user`. The `client` fixture
therefore also overrides that dependency so existing endpoint tests keep
exercising business logic without each one having to mint a real JWT; the
auth flow itself (register/login/refresh) and the "no token" 401 behavior
are covered separately using a real token / the unauthenticated app.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user, get_db
from app.core.security import hash_password
from app.db.models.base import Base
from app.db.models.user import User
from app.main import app
from app.repositories.user_repository import UserRepository

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


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
async def test_user(db_session: AsyncSession) -> User:
    """Persist and return a real user row to authenticate test requests as."""
    now = datetime.now(UTC)
    return await UserRepository(db_session).create(
        email="test.user@example.com",
        hashed_password=hash_password("test-password-123"),
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

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def unauthenticated_client(db_session) -> TestClient:
    """Return a TestClient with only `get_db` overridden (no auth override).

    Used to verify that protected endpoints correctly reject requests with
    no/invalid bearer token, and to exercise the real register/login/refresh
    flow end-to-end.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
