"""Tests for the TRIAL-plan geocoding quota: PLAN_GEOCODE_LIMITS enforcement
on delivery create/update/import (each calls the paid Google Geocoding API
once), and MAX_IMPORT_ROWS_PER_REQUEST as a flat per-request safety cap."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import MAX_IMPORT_ROWS_PER_REQUEST, PLAN_GEOCODE_LIMITS, SubscriptionPlan
from app.db.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository
from app.services.geocoding.client import GoogleGeocodingClient

TRIAL_GEOCODE_LIMIT = PLAN_GEOCODE_LIMITS[SubscriptionPlan.TRIAL]


async def _seed_geocode_count(db_session: AsyncSession, organization: Organization, amount: int) -> None:
    """Bump `geocode_calls_count` by `amount` directly (limit=None => always
    succeeds), instead of driving `amount` real geocode-consuming requests
    through the API — this is only meant to position the counter, not to
    exercise the request path."""
    await OrganizationRepository(db_session).try_consume_quota(
        organization.id, counter_column="geocode_calls_count", limit=None, amount=amount
    )


@pytest.fixture
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GoogleGeocodingClient,
        "geocode",
        AsyncMock(side_effect=[(50.46 + i * 0.001, 30.53 + i * 0.001) for i in range(1000)]),
    )


def _create_delivery(client: TestClient, customer_name: str) -> object:
    return client.post(
        "/api/v1/deliveries/",
        json={
            "customer_name": customer_name,
            "address": f"Kyiv, {customer_name} street",
            "weight_kg": 5.0,
            "volume_m3": 0.1,
            "unloading_minutes": 5,
        },
    )


async def test_delivery_creation_blocked_once_geocode_quota_is_exhausted(
    client: TestClient,
    mock_geocode: None,
    test_organization: Organization,
    db_session: AsyncSession,
) -> None:
    # Seed straight to one-short-of-the-cap instead of driving
    # TRIAL_GEOCODE_LIMIT real creates through the API.
    await _seed_geocode_count(db_session, test_organization, TRIAL_GEOCODE_LIMIT - 1)

    last_allowed = _create_delivery(client, "Last Allowed")
    assert last_allowed.status_code == 200, last_allowed.text

    blocked = _create_delivery(client, "One Too Many")
    assert blocked.status_code == 403
    assert "limit" in blocked.json()["detail"].lower()


def test_delivery_update_address_consumes_geocode_quota(
    client: TestClient, mock_geocode: None
) -> None:
    created = _create_delivery(client, "Original").json()

    response = client.put(
        f"/api/v1/deliveries/{created['id']}",
        json={"address": "Kyiv, New Address 1"},
    )
    assert response.status_code == 200


def test_import_rejects_files_over_the_row_cap(client: TestClient) -> None:
    csv_content = "customer_name,address\n" + "\n".join(
        f"Row {i},Kyiv Address {i}" for i in range(MAX_IMPORT_ROWS_PER_REQUEST + 1)
    )
    response = client.post(
        "/api/v1/deliveries/import",
        files={"file": ("bulk.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 400
    assert "limit" in response.json()["detail"].lower()


async def test_import_stops_creating_rows_once_geocode_quota_is_exhausted(
    client: TestClient,
    mock_geocode: None,
    test_organization: Organization,
    db_session: AsyncSession,
) -> None:
    # Seed to 3-short-of-the-cap so only a handful of import rows are needed
    # to prove "stop once exhausted", regardless of how large
    # TRIAL_GEOCODE_LIMIT is configured.
    remaining_allowance = 3
    extra_rows = 4
    await _seed_geocode_count(db_session, test_organization, TRIAL_GEOCODE_LIMIT - remaining_allowance)

    row_count = remaining_allowance + extra_rows
    csv_content = "customer_name,address\n" + "\n".join(
        f"Row {i},Kyiv Address {i}" for i in range(row_count)
    )
    response = client.post(
        "/api/v1/deliveries/import",
        files={"file": ("bulk.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == row_count
    assert body["imported"] == remaining_allowance
    assert body["failed"] == extra_rows
