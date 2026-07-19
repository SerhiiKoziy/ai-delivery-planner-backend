"""Tests for the TRIAL-plan geocoding quota: PLAN_GEOCODE_LIMITS enforcement
on delivery create/update/import (each calls the paid Google Geocoding API
once), and MAX_IMPORT_ROWS_PER_REQUEST as a flat per-request safety cap."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.plans import MAX_IMPORT_ROWS_PER_REQUEST, PLAN_GEOCODE_LIMITS, SubscriptionPlan
from app.services.geocoding.client import GoogleGeocodingClient

TRIAL_GEOCODE_LIMIT = PLAN_GEOCODE_LIMITS[SubscriptionPlan.TRIAL]


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


def test_delivery_creation_blocked_once_geocode_quota_is_exhausted(
    client: TestClient, mock_geocode: None
) -> None:
    for i in range(TRIAL_GEOCODE_LIMIT):
        response = _create_delivery(client, f"Customer {i}")
        assert response.status_code == 200, response.text

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


def test_import_stops_creating_rows_once_geocode_quota_is_exhausted(
    client: TestClient, mock_geocode: None
) -> None:
    row_count = TRIAL_GEOCODE_LIMIT + 3
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
    assert body["imported"] == TRIAL_GEOCODE_LIMIT
    assert body["failed"] == row_count - TRIAL_GEOCODE_LIMIT
