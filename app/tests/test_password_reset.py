"""Tests for the forgot-password -> emailed link -> reset-password flow."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import router as auth_router
from app.core.security import (
    create_email_verification_token,
    create_password_reset_token,
    verify_password,
)
from app.db.models.user import User
from app.repositories.user_repository import UserRepository

GENERIC_MESSAGE = "If an account with this email exists, we've sent a password reset link."
OLD_PASSWORD = "test-password-123"
NEW_PASSWORD = "brand-new-password-456"


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture (email, token) for every reset email instead of sending it."""
    sent: list[tuple[str, str]] = []

    async def _capture(email: str, token: str) -> None:
        sent.append((email, token))

    monkeypatch.setattr(auth_router, "send_password_reset_email", _capture)
    return sent


@pytest.fixture
async def verified_user(db_session: AsyncSession, test_user: User) -> User:
    return await UserRepository(db_session).update(test_user.id, is_verified=True)


def _login(client: TestClient, email: str, password: str) -> int:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


def test_forgot_password_emails_a_reset_link(
    client: TestClient, test_user: User, sent_emails: list
) -> None:
    response = client.post("/api/v1/auth/forgot-password", json={"email": test_user.email})

    assert response.status_code == 200
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert len(sent_emails) == 1
    assert sent_emails[0][0] == test_user.email


def test_forgot_password_gives_the_same_answer_for_unknown_emails(
    client: TestClient, sent_emails: list
) -> None:
    response = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})

    assert response.status_code == 200
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert sent_emails == []


def test_reset_password_sets_the_new_password_and_logs_in(
    client: TestClient, verified_user: User, sent_emails: list
) -> None:
    client.post("/api/v1/auth/forgot-password", json={"email": verified_user.email})
    token = sent_emails[0][1]

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    assert "access_token" in response.json()
    assert _login(client, verified_user.email, NEW_PASSWORD) == 200
    assert _login(client, verified_user.email, OLD_PASSWORD) == 401


def test_reset_link_works_only_once(client: TestClient, verified_user: User) -> None:
    token = create_password_reset_token(str(verified_user.id), verified_user.hashed_password)
    body = {"token": token, "new_password": NEW_PASSWORD}

    first = client.post("/api/v1/auth/reset-password", json=body)
    second = client.post("/api/v1/auth/reset-password", json={**body, "new_password": "x" * 12})

    assert first.status_code == 200
    assert second.status_code == 400
    assert _login(client, verified_user.email, NEW_PASSWORD) == 200


def test_expired_reset_link_is_rejected(client: TestClient, verified_user: User) -> None:
    token = create_password_reset_token(
        str(verified_user.id), verified_user.hashed_password, expires_delta=timedelta(seconds=-1)
    )

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400
    assert _login(client, verified_user.email, OLD_PASSWORD) == 200


def test_other_token_types_cannot_reset_a_password(client: TestClient, test_user: User) -> None:
    token = create_email_verification_token(str(test_user.id))

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400


def test_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/reset-password", json={"token": "not-a-token", "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400


def test_new_password_must_be_at_least_8_characters(client: TestClient, test_user: User) -> None:
    token = create_password_reset_token(str(test_user.id), test_user.hashed_password)

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "short"}
    )

    assert response.status_code == 422


async def test_reset_verifies_an_unverified_account(
    client: TestClient, test_user: User, db_session: AsyncSession
) -> None:
    assert test_user.is_verified is False
    token = create_password_reset_token(str(test_user.id), test_user.hashed_password)

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    user = await UserRepository(db_session).get(test_user.id)
    assert user.is_verified is True
    assert verify_password(NEW_PASSWORD, user.hashed_password)
