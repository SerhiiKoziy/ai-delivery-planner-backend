"""Shared pytest fixtures: test client and test DB session stubs."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Return a FastAPI TestClient for synchronous endpoint tests."""
    return TestClient(app)


@pytest.fixture
async def db_session():
    """Yield a test database session. Stub — wire up a test DB/transaction rollback later."""
    raise NotImplementedError
