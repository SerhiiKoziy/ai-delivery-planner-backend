"""Tests for TRIAL's combined "API requests" cap: PLAN_API_REQUEST_LIMITS
enforcement across routes + geocode + ai_calls together (15 total for
TRIAL), which binds well before any single per-category limit (50 routes,
500 geocode calls, 20 AI calls — see test_route_quota.py, test_delivery_quota.py,
test_ai_quota.py for those in isolation)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PLAN_API_REQUEST_LIMITS, SubscriptionPlan
from app.db.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository

TRIAL_COMBINED_LIMIT = PLAN_API_REQUEST_LIMITS[SubscriptionPlan.TRIAL]


async def test_ai_call_blocked_by_combined_cap_before_its_own_limit(
    ai_client, route_with_stops: dict, test_organization: Organization, db_session: AsyncSession
) -> None:
    """AI calls alone are capped at 20 for TRIAL, but the combined cap (15)
    is lower — repeated /ai/explain calls must hit it first."""
    route_id = str(route_with_stops["route_id"])

    for i in range(TRIAL_COMBINED_LIMIT):
        response = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
        assert response.status_code == 200, f"call {i}: {response.text}"

    blocked = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
    assert blocked.status_code == 403
    assert "limit" in blocked.json()["detail"].lower()


async def test_combined_cap_applies_across_categories_not_just_one(
    ai_client, route_with_stops: dict, test_organization: Organization, db_session: AsyncSession
) -> None:
    """Usage from routes/geocode counts toward the same combined cap as AI
    calls — one short of the cap via routes+geocode, an AI call still fits,
    then the next one is blocked."""
    remaining_allowance = 1
    already_used = TRIAL_COMBINED_LIMIT - remaining_allowance
    org_repo = OrganizationRepository(db_session)
    await org_repo.try_consume_quota(
        test_organization.id, counter_column="routes_generated_count", limit=None, amount=already_used
    )

    route_id = str(route_with_stops["route_id"])
    last_allowed = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
    assert last_allowed.status_code == 200, last_allowed.text

    blocked = ai_client.post("/api/v1/ai/explain", json={"route_id": route_id})
    assert blocked.status_code == 403
    assert "limit" in blocked.json()["detail"].lower()


def test_me_reports_combined_trial_limit(client) -> None:
    response = client.get("/api/v1/organizations/me")
    assert response.status_code == 200
    body = response.json()
    assert body["apiRequestsLimit"] == TRIAL_COMBINED_LIMIT
    assert body["apiRequestsRemaining"] == TRIAL_COMBINED_LIMIT
