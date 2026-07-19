"""Integration tests for the /api/v1/depots endpoints.

Uses the in-memory SQLite `client` fixture from conftest.py.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PLAN_GEOCODE_LIMITS, SubscriptionPlan
from app.db.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository
from app.services.geocoding.client import GeocodeResult, GoogleGeocodingClient

TRIAL_GEOCODE_LIMIT = PLAN_GEOCODE_LIMITS[SubscriptionPlan.TRIAL]


def _make_payload(**overrides) -> dict:
    payload = {
        "address": "Kyiv, Khreshchatyk 1",
        "latitude": 50.45,
        "longitude": 30.52,
    }
    payload.update(overrides)
    return payload


def test_create_depot_returns_expected_fields(client: TestClient) -> None:
    response = client.post("/api/v1/depots/", json=_make_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["address"] == "Kyiv, Khreshchatyk 1"
    assert body["latitude"] == 50.45
    assert body["longitude"] == 30.52
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_list_depots_returns_newest_first(client: TestClient) -> None:
    first = client.post("/api/v1/depots/", json=_make_payload(address="First")).json()
    second = client.post("/api/v1/depots/", json=_make_payload(address="Second")).json()

    response = client.get("/api/v1/depots/")
    assert response.status_code == 200

    body = response.json()
    assert len(body) == 2
    ids = [row["id"] for row in body]
    assert ids == [second["id"], first["id"]]


def test_get_depot_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/depots/", json=_make_payload()).json()

    response = client.get(f"/api/v1/depots/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_depot_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/depots/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_depot_changes_only_specified_field(client: TestClient) -> None:
    created = client.post("/api/v1/depots/", json=_make_payload()).json()

    response = client.put(f"/api/v1/depots/{created['id']}", json={"address": "New Address"})
    assert response.status_code == 200

    body = response.json()
    assert body["address"] == "New Address"
    assert body["latitude"] == created["latitude"]
    assert body["longitude"] == created["longitude"]


def test_update_depot_not_found(client: TestClient) -> None:
    response = client.put(f"/api/v1/depots/{uuid.uuid4()}", json={"address": "Nobody"})
    assert response.status_code == 404


def test_delete_depot(client: TestClient) -> None:
    created = client.post("/api/v1/depots/", json=_make_payload()).json()

    delete_response = client.delete(f"/api/v1/depots/{created['id']}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/depots/{created['id']}")
    assert get_response.status_code == 404


def test_delete_depot_not_found(client: TestClient) -> None:
    response = client.delete(f"/api/v1/depots/{uuid.uuid4()}")
    assert response.status_code == 404


def test_geocode_depot_address_returns_coordinates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        GoogleGeocodingClient,
        "geocode_full",
        AsyncMock(
            return_value=GeocodeResult(
                latitude=50.4501, longitude=30.5234, formatted_address="Khreshchatyk St, Kyiv, Ukraine"
            )
        ),
    )
    response = client.post("/api/v1/depots/geocode", json={"address": "Kyiv, Khreshchatyk 1"})
    assert response.status_code == 200
    body = response.json()
    assert body["latitude"] == 50.4501
    assert body["longitude"] == 30.5234
    assert body["formatted_address"] == "Khreshchatyk St, Kyiv, Ukraine"


def test_geocode_depot_address_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GoogleGeocodingClient, "geocode_full", AsyncMock(return_value=None))
    response = client.post("/api/v1/depots/geocode", json={"address": "Nowhere"})
    assert response.status_code == 404


async def test_geocode_depot_address_blocked_once_quota_exhausted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_organization: Organization,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(
        GoogleGeocodingClient,
        "geocode_full",
        AsyncMock(
            return_value=GeocodeResult(latitude=50.45, longitude=30.52, formatted_address="Kyiv")
        ),
    )
    await OrganizationRepository(db_session).try_consume_quota(
        test_organization.id,
        counter_column="geocode_calls_count",
        limit=None,
        amount=TRIAL_GEOCODE_LIMIT,
    )

    response = client.post("/api/v1/depots/geocode", json={"address": "Kyiv, Khreshchatyk 1"})
    assert response.status_code == 403
    assert "limit" in response.json()["detail"].lower()
