"""Tests for the TRIAL-plan route-generation quota: PLAN_ROUTE_LIMITS enforcement
via `require_route_quota`, the counter increment on POST /routes/optimize, and
the GET /organizations/me usage read model."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.plans import PLAN_ROUTE_LIMITS, SubscriptionPlan
from app.services.geocoding.client import GoogleGeocodingClient

DEPOT_LAT, DEPOT_LNG = 50.4501, 30.5234
TRIAL_LIMIT = PLAN_ROUTE_LIMITS[SubscriptionPlan.TRIAL]


@pytest.fixture
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    # A single, distinct coordinate is handed out per geocode call, in the
    # order deliveries are created below.
    monkeypatch.setattr(
        GoogleGeocodingClient,
        "geocode",
        AsyncMock(side_effect=[(50.46 + i * 0.001, 30.53 + i * 0.001) for i in range(50)]),
    )


def _create_depot(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/depots/",
        json={"address": "Kyiv depot", "latitude": DEPOT_LAT, "longitude": DEPOT_LNG},
    )
    assert response.status_code == 200
    return response.json()


def _create_driver(client: TestClient, name: str) -> dict:
    response = client.post("/api/v1/drivers/", json={"name": name, "phone": "+380501112233"})
    assert response.status_code == 200
    return response.json()


def _create_vehicle(client: TestClient, plate: str, driver_id: str) -> dict:
    response = client.post(
        "/api/v1/vehicles/",
        json={
            "plate_number": plate,
            "capacity_weight_kg": 500.0,
            "capacity_volume_m3": 5.0,
            "driver_id": driver_id,
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_delivery(client: TestClient, customer_name: str) -> dict:
    response = client.post(
        "/api/v1/deliveries/",
        json={
            "customer_name": customer_name,
            "address": f"Kyiv, {customer_name} street",
            "weight_kg": 5.0,
            "volume_m3": 0.1,
            "unloading_minutes": 5,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def single_driver_scenario(client: TestClient, mock_geocode: None) -> dict:
    """Depot + 1 driver + 1 vehicle: every optimize() call below produces
    exactly one Route, so the quota counter advances by 1 per call."""
    depot = _create_depot(client)
    driver = _create_driver(client, "Solo Driver")
    vehicle = _create_vehicle(client, "AA1111AA", driver["id"])
    return {"depot": depot, "driver": driver, "vehicle": vehicle}


def _optimize(client: TestClient, scenario: dict, delivery: dict) -> object:
    payload = {
        "delivery_ids": [delivery["id"]],
        "vehicle_ids": [scenario["vehicle"]["id"]],
        "depot_id": scenario["depot"]["id"],
        "return_to_depot": True,
    }
    return client.post("/api/v1/routes/optimize", json=payload)


def test_new_organization_defaults_to_trial_plan_with_full_quota(client: TestClient) -> None:
    response = client.get("/api/v1/organizations/me")
    assert response.status_code == 200
    body = response.json()
    assert body["subscriptionPlan"] == "trial"
    assert body["routesGeneratedCount"] == 0
    assert body["routesLimit"] == TRIAL_LIMIT
    assert body["routesRemaining"] == TRIAL_LIMIT


def test_optimize_increments_quota_counter(client: TestClient, single_driver_scenario: dict) -> None:
    delivery = _create_delivery(client, "Customer A")
    response = _optimize(client, single_driver_scenario, delivery)
    assert response.status_code == 200
    assert len(response.json()["routes"]) == 1

    org = client.get("/api/v1/organizations/me").json()
    assert org["routesGeneratedCount"] == 1
    assert org["routesRemaining"] == TRIAL_LIMIT - 1


def test_optimize_blocked_once_trial_quota_is_exhausted(
    client: TestClient, single_driver_scenario: dict
) -> None:
    for i in range(TRIAL_LIMIT):
        delivery = _create_delivery(client, f"Customer {i}")
        response = _optimize(client, single_driver_scenario, delivery)
        assert response.status_code == 200, response.text

    org = client.get("/api/v1/organizations/me").json()
    assert org["routesGeneratedCount"] == TRIAL_LIMIT
    assert org["routesRemaining"] == 0

    one_more_delivery = _create_delivery(client, "One Too Many")
    blocked_response = _optimize(client, single_driver_scenario, one_more_delivery)
    assert blocked_response.status_code == 403
    assert "limit" in blocked_response.json()["detail"].lower()
