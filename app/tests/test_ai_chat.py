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


def test_chat_persists_and_replays_history(
    ai_client: TestClient, route_with_stops: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    route_id = str(route_with_stops["route_id"])

    first = ai_client.post(
        "/api/v1/ai/chat",
        json={"message": "Why is this stop scheduled first?", "route_id": route_id},
    )
    assert first.status_code == 200

    second = ai_client.post(
        "/api/v1/ai/chat",
        json={"message": "And what about the second one?", "route_id": route_id},
    )
    assert second.status_code == 200

    # The second call's prompt must include the first turn's exchange as
    # history, followed by the new user message.
    assert len(mock_openai_client.calls) == 2
    second_call_messages = mock_openai_client.calls[1]["messages"]
    roles_and_content = [(m["role"], m["content"]) for m in second_call_messages]
    assert ("user", "Why is this stop scheduled first?") in roles_and_content
    assert ("assistant", mock_openai_client.plain_reply) in roles_and_content
    assert second_call_messages[-1] == {
        "role": "user",
        "content": "And what about the second one?",
    }

    history = ai_client.get(f"/api/v1/ai/chat/{route_id}/history")
    assert history.status_code == 200
    body = history.json()
    assert [m["role"] for m in body] == ["user", "assistant", "user", "assistant"]
    assert body[0]["content"] == "Why is this stop scheduled first?"
    assert body[-1]["content"] == mock_openai_client.plain_reply
