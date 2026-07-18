"""Integration tests for POST /api/v1/ai/explain.

Uses the `ai_client` fixture (fake OpenAI client, no network) and the
`route_with_stops` fixture (a minimal persisted Depot/Delivery/Route/RouteStop)
from conftest.py.
"""

import uuid

from fastapi.testclient import TestClient

from app.tests.conftest import FakeOpenAIClient


def test_explain_returns_explanation_for_known_route(
    ai_client: TestClient, route_with_stops: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    response = ai_client.post(
        "/api/v1/ai/explain",
        json={"route_id": str(route_with_stops["route_id"])},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["explanation"] == mock_openai_client.plain_reply

    assert len(mock_openai_client.calls) == 1
    sent_messages = mock_openai_client.calls[0]["messages"]
    # The route summary (customer name, priority, stop sequence) must have
    # been included as context sent to the model.
    joined = "\n".join(m["content"] for m in sent_messages)
    assert "Acme LLC" in joined
    assert "high" in joined.lower()


def test_explain_404s_for_unknown_route(ai_client: TestClient) -> None:
    response = ai_client.post(
        "/api/v1/ai/explain",
        json={"route_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
