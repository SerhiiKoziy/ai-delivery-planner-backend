"""Integration tests for POST /api/v1/ai/chat.

Uses the `ai_client` fixture (fake OpenAI client, no network) and the
`route_with_stops` fixture (a minimal persisted Depot/Delivery/Route/RouteStop)
from conftest.py.
"""

import uuid

from fastapi.testclient import TestClient

from app.tests.conftest import FakeOpenAIClient


def test_chat_returns_reply_for_known_route(
    ai_client: TestClient, route_with_stops: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    response = ai_client.post(
        "/api/v1/ai/chat",
        json={
            "message": "Why is this stop scheduled first?",
            "route_id": str(route_with_stops["route_id"]),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == mock_openai_client.plain_reply

    # The user's message must have reached the model as the final turn.
    assert len(mock_openai_client.calls) == 1
    sent_messages = mock_openai_client.calls[0]["messages"]
    assert sent_messages[-1]["role"] == "user"
    assert sent_messages[-1]["content"] == "Why is this stop scheduled first?"


def test_chat_404s_for_unknown_route(ai_client: TestClient) -> None:
    response = ai_client.post(
        "/api/v1/ai/chat",
        json={"message": "hello", "route_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
