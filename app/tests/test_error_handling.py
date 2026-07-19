"""Tests for centralized error handling (app/core/error_handlers.py): every
API response — including bugs and third-party outages, not just deliberate
`raise HTTPException` calls — comes back as a clear `{"detail": "<string>"}`
JSON body, never a raw traceback, plain-text body, or nested validation-error
list the frontend can't display."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_ai_model, get_current_user, get_db
from app.db.models.user import User
from app.main import app
from app.services.ai.client import get_openai_client
from app.services.deliveries.service import DeliveryService
from app.tests.conftest import FakeOpenAIClient


@pytest.fixture
def lenient_client(db_session: AsyncSession, test_user: User) -> TestClient:
    """Like the shared `client` fixture, but with `raise_server_exceptions=False`.

    Starlette's ServerErrorMiddleware always re-raises an unhandled exception
    after building the registered handler's response (so tools like pytest
    can still see it by default) — these tests want to assert on the actual
    HTTP response our handler produced, not on the propagated exception.
    """

    async def _override_get_db():
        yield db_session

    async def _override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def lenient_ai_client(
    lenient_client: TestClient, mock_openai_client: FakeOpenAIClient
) -> TestClient:
    def _override_get_openai_client() -> FakeOpenAIClient:
        return mock_openai_client

    def _override_get_ai_model() -> str:
        return "gpt-4.1-mini-test"

    app.dependency_overrides[get_openai_client] = _override_get_openai_client
    app.dependency_overrides[get_ai_model] = _override_get_ai_model
    try:
        yield lenient_client
    finally:
        app.dependency_overrides.pop(get_openai_client, None)
        app.dependency_overrides.pop(get_ai_model, None)


def test_validation_error_returns_a_readable_string_detail(client: TestClient) -> None:
    # Missing the required "address" field on DeliveryCreate.
    response = client.post(
        "/api/v1/deliveries/",
        json={"customer_name": "Test Customer"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "address" in detail


def test_unhandled_exception_returns_clean_generic_500_not_a_traceback(
    lenient_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(self, delivery_id):
        raise RuntimeError("some internal detail that must never reach the client")

    monkeypatch.setattr(DeliveryService, "get", _boom)

    response = lenient_client.get(f"/api/v1/deliveries/{uuid.uuid4()}")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body == {"detail": "Something went wrong on our end. Please try again."}
    assert "RuntimeError" not in response.text
    assert "some internal detail" not in response.text


def test_openai_failure_returns_clean_503_not_the_sdk_error(
    lenient_ai_client: TestClient,
    mock_openai_client: FakeOpenAIClient,
    route_with_stops: dict,
) -> None:
    async def _raise_connection_error(*args, **kwargs):
        raise APIConnectionError(
            message="upstream had a bad day, includes internal diagnostic info",
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )

    mock_openai_client._create = _raise_connection_error

    response = lenient_ai_client.post(
        "/api/v1/ai/explain",
        json={"route_id": str(route_with_stops["route_id"])},
    )
    assert response.status_code == 503
    body = response.json()
    assert body == {
        "detail": "The AI service is temporarily unavailable. Please try again shortly."
    }
    assert "upstream had a bad day" not in response.text
