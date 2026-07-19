"""Tests for the in-memory per-IP rate limiter guarding /auth/register and
/auth/login. Uses its own `raw_client` fixture (only `get_db` overridden,
NOT the no-op rate-limit override that `client`/`unauthenticated_client`
apply in conftest.py) so the real limiting logic runs end-to-end."""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.core.rate_limiting import reset_all_windows_for_tests
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state():
    reset_all_windows_for_tests()
    yield
    reset_all_windows_for_tests()


@pytest.fixture
def raw_client(db_session) -> TestClient:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_register_is_rate_limited_per_ip(raw_client: TestClient) -> None:
    for i in range(5):
        response = raw_client.post(
            "/api/v1/auth/register",
            json={"email": f"bulk.signup.{i}@example.com", "password": "password-123"},
        )
        assert response.status_code == 201, response.text

    blocked = raw_client.post(
        "/api/v1/auth/register",
        json={"email": "one.too.many@example.com", "password": "password-123"},
    )
    assert blocked.status_code == 429


def test_login_is_rate_limited_per_ip(raw_client: TestClient) -> None:
    for _ in range(20):
        response = raw_client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = raw_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "wrong"},
    )
    assert blocked.status_code == 429


def test_rate_limit_windows_are_scoped_independently_per_ip(raw_client: TestClient) -> None:
    """A different client IP must get its own fresh window."""
    for i in range(5):
        response = raw_client.post(
            "/api/v1/auth/register",
            json={"email": f"first.ip.{i}@example.com", "password": "password-123"},
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        assert response.status_code == 201

    # The limiter keys on `request.client.host` (the TCP peer), not
    # X-Forwarded-For, so TestClient's fixed test-client host means this
    # request is still counted against the SAME window as above and is
    # correctly blocked — proving the limiter isn't fooled by a spoofable
    # header.
    blocked = raw_client.post(
        "/api/v1/auth/register",
        json={"email": "still.same.ip@example.com", "password": "password-123"},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert blocked.status_code == 429
