"""Tests for the register -> verify-email -> login flow: new accounts start
unverified and can't log in until the emailed verification token is
redeemed via POST /auth/verify-email."""

from fastapi.testclient import TestClient

from app.core.security import create_access_token, create_email_verification_token


def test_register_returns_pending_verification_not_tokens(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "new.signup@example.com", "password": "password-123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "access_token" not in body
    assert body["email"] == "new.signup@example.com"
    assert "user_id" in body


def test_login_before_verification_is_rejected(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "unverified@example.com", "password": "password-123"},
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": "password-123"},
    )
    assert response.status_code == 403


def test_verify_email_activates_account_and_returns_tokens(client: TestClient) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "verify.me@example.com", "password": "password-123"},
    )
    user_id = register_response.json()["user_id"]
    token = create_email_verification_token(user_id)

    verify_response = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify_response.status_code == 200
    assert "access_token" in verify_response.json()

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "verify.me@example.com", "password": "password-123"},
    )
    assert login_response.status_code == 200


def test_verify_email_is_idempotent(client: TestClient) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "verify.twice@example.com", "password": "password-123"},
    )
    token = create_email_verification_token(register_response.json()["user_id"])

    first = client.post("/api/v1/auth/verify-email", json={"token": token})
    second = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert second.status_code == 200


def test_verify_email_rejects_garbage_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert response.status_code == 401


def test_verify_email_rejects_wrong_token_type(client: TestClient) -> None:
    # An access token (not an email_verification token) must not work here.
    access_token = create_access_token("11111111-1111-1111-1111-111111111111")
    response = client.post("/api/v1/auth/verify-email", json={"token": access_token})
    assert response.status_code == 401


def test_verify_email_rejects_unknown_user(client: TestClient) -> None:
    token = create_email_verification_token("22222222-2222-2222-2222-222222222222")
    response = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 401
