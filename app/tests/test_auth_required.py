"""Verify protected routers reject unauthenticated requests and accept a
real, freshly-issued JWT.

Uses the `unauthenticated_client` fixture from conftest.py, which overrides
only `get_db` (in-memory SQLite) and leaves `get_current_user` wired to the
real JWT-decoding implementation.
"""

from fastapi.testclient import TestClient

from app.core.security import create_email_verification_token

PROTECTED_ENDPOINTS = [
    ("GET", "/api/v1/deliveries/"),
    ("GET", "/api/v1/drivers/"),
    ("GET", "/api/v1/vehicles/"),
    ("GET", "/api/v1/depots/"),
    ("GET", "/api/v1/dashboard/overview"),
]


def test_public_auth_endpoints_do_not_require_a_token(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "new.user@example.com", "password": "s3cret-password"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.user@example.com"
    assert "user_id" in response.json()


def test_protected_endpoints_reject_missing_token(unauthenticated_client: TestClient) -> None:
    for method, path in PROTECTED_ENDPOINTS:
        response = unauthenticated_client.request(method, path)
        assert response.status_code == 401, f"{method} {path} did not require auth"


def test_protected_endpoints_reject_garbage_token(unauthenticated_client: TestClient) -> None:
    headers = {"Authorization": "Bearer not-a-real-token"}
    for method, path in PROTECTED_ENDPOINTS:
        response = unauthenticated_client.request(method, path, headers=headers)
        assert response.status_code == 401, f"{method} {path} accepted a garbage token"


def test_protected_endpoint_accepts_a_real_token(unauthenticated_client: TestClient) -> None:
    register_response = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "authed.user@example.com", "password": "s3cret-password"},
    )
    assert register_response.status_code == 201
    user_id = register_response.json()["user_id"]

    verify_response = unauthenticated_client.post(
        "/api/v1/auth/verify-email",
        json={"token": create_email_verification_token(user_id)},
    )
    assert verify_response.status_code == 200
    access_token = verify_response.json()["access_token"]

    response = unauthenticated_client.get(
        "/api/v1/deliveries/",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
