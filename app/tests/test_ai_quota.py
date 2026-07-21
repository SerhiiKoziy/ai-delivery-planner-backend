"""Tests for the TRIAL-plan AI-call quota: PLAN_AI_CALL_LIMITS enforcement via
`require_ai_quota`, applied to /ai/explain, /ai/chat, /ai/analyze, /ai/replan
(each consumes 1 unit up front, before any OpenAI call), but NOT to the
read-only GET /ai/chat/{route_id}/history."""

import pytest
from fastapi.testclient import TestClient

from app.core import plans
from app.core.plans import PLAN_AI_CALL_LIMITS, SubscriptionPlan

TRIAL_AI_LIMIT = PLAN_AI_CALL_LIMITS[SubscriptionPlan.TRIAL]


@pytest.fixture(autouse=True)
def _disable_combined_quota_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module drives ai_calls_count up to TRIAL_AI_LIMIT (20) to test
    PLAN_AI_CALL_LIMITS in isolation. TRIAL also has a much lower combined
    cap (see PLAN_API_REQUEST_LIMITS / test_api_request_quota.py) which would
    otherwise block these calls long before the AI-specific limit is reached.
    """
    monkeypatch.setitem(plans.PLAN_API_REQUEST_LIMITS, SubscriptionPlan.TRIAL, None)


def test_explain_blocked_once_ai_quota_is_exhausted(
    ai_client: TestClient, route_with_stops: dict
) -> None:
    route_id = str(route_with_stops["route_id"])
    for i in range(TRIAL_AI_LIMIT):
        response = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
        assert response.status_code == 200, f"call {i}: {response.text}"

    blocked = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
    assert blocked.status_code == 403
    assert "limit" in blocked.json()["detail"].lower()


def test_chat_history_is_not_quota_gated(ai_client: TestClient, route_with_stops: dict) -> None:
    """Reading history makes no OpenAI call and must never consume quota,
    regardless of how many times it's called."""
    route_id = str(route_with_stops["route_id"])
    for _ in range(TRIAL_AI_LIMIT + 5):
        response = ai_client.get(f"/api/v1/ai/chat/{route_id}/history")
        assert response.status_code == 200

    # The real quota-consuming endpoint must still have its full allowance.
    still_allowed = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
    assert still_allowed.status_code == 200
