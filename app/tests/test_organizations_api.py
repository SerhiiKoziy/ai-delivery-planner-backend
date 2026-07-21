"""Integration tests for GET /api/v1/organizations/me."""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import SubscriptionPlan
from app.db.models.organization import Organization


def test_me_reports_trial_plan_and_quotas(client: TestClient) -> None:
    response = client.get("/api/v1/organizations/me")
    assert response.status_code == 200

    body = response.json()
    assert body["subscriptionPlan"] == "trial"
    # TRIAL: routes=50, geocode=500, aiCalls=20 (see app/core/plans.py)
    assert body["routesLimit"] == 50
    assert body["routesRemaining"] == 50
    assert body["geocodeCallsLimit"] == 500
    assert body["geocodeCallsRemaining"] == 500
    assert body["aiCallsLimit"] == 20
    assert body["aiCallsRemaining"] == 20
    assert body["apiRequestsUsed"] == 0
    # TRIAL has an explicit combined cap (15) below the sum of its
    # per-category limits (570) — see PLAN_API_REQUEST_LIMITS.
    assert body["apiRequestsLimit"] == 15
    assert body["apiRequestsRemaining"] == 15


async def test_me_reflects_consumed_quota(
    client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    test_organization.routes_generated_count = 3
    test_organization.geocode_calls_count = 5
    test_organization.ai_calls_count = 2
    db_session.add(test_organization)
    await db_session.commit()

    response = client.get("/api/v1/organizations/me")
    assert response.status_code == 200

    body = response.json()
    assert body["apiRequestsUsed"] == 10
    assert body["apiRequestsLimit"] == 15
    assert body["apiRequestsRemaining"] == 5


async def test_me_unlimited_plan_has_no_combined_limit(
    client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    test_organization.subscription_plan = SubscriptionPlan.SMALL
    db_session.add(test_organization)
    await db_session.commit()

    response = client.get("/api/v1/organizations/me")
    assert response.status_code == 200

    body = response.json()
    assert body["routesLimit"] is None
    assert body["apiRequestsLimit"] is None
    assert body["apiRequestsRemaining"] is None
