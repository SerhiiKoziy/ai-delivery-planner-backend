"""Integration tests for the route optimizer through the real API:
POST /api/v1/routes/optimize and GET /api/v1/routes/{route_id}.

Uses the in-memory SQLite `client` fixture from conftest.py. Geocoding is
monkeypatched (as in test_deliveries_api.py) so each created delivery gets a
distinct, deterministic Kyiv-area coordinate without any network access.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.services.geocoding.client import GoogleGeocodingClient

DEPOT_LAT, DEPOT_LNG = 50.4501, 30.5234

DELIVERY_COORDINATES = [
    (50.4600, 30.5300),
    (50.4400, 30.5100),
    (50.4550, 30.5000),
    (50.4700, 30.5400),
]


@pytest.fixture
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GoogleGeocodingClient,
        "geocode",
        AsyncMock(side_effect=list(DELIVERY_COORDINATES)),
    )


def _create_depot(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/depots/",
        json={"address": "Kyiv depot", "latitude": DEPOT_LAT, "longitude": DEPOT_LNG},
    )
    assert response.status_code == 200
    return response.json()


def _create_driver(client: TestClient, name: str) -> dict:
    response = client.post(
        "/api/v1/drivers/",
        json={"name": name, "phone": "+380501112233"},
    )
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
def scenario(client: TestClient, mock_geocode: None) -> dict:
    """Depot + 2 drivers + 2 vehicles + 4 geocoded deliveries."""
    depot = _create_depot(client)
    driver1 = _create_driver(client, "Driver One")
    driver2 = _create_driver(client, "Driver Two")
    vehicle1 = _create_vehicle(client, "AA1111AA", driver1["id"])
    vehicle2 = _create_vehicle(client, "BB2222BB", driver2["id"])
    deliveries = [_create_delivery(client, f"Customer {i}") for i in range(len(DELIVERY_COORDINATES))]

    return {
        "depot": depot,
        "drivers": [driver1, driver2],
        "vehicles": [vehicle1, vehicle2],
        "deliveries": deliveries,
    }


def test_optimize_assigns_or_reports_every_requested_delivery(scenario: dict, client: TestClient) -> None:
    payload = {
        "delivery_ids": [d["id"] for d in scenario["deliveries"]],
        "vehicle_ids": [v["id"] for v in scenario["vehicles"]],
        "depot_id": scenario["depot"]["id"],
        "return_to_depot": True,
    }
    response = client.post("/api/v1/routes/optimize", json=payload)
    assert response.status_code == 200

    body = response.json()
    assert len(body["routes"]) >= 1

    requested_ids = {d["id"] for d in scenario["deliveries"]}
    covered_ids = {sid for route in body["routes"] for sid in [s["delivery_id"] for s in route["stops"]]}
    covered_ids |= set(body["unassigned_delivery_ids"])
    assert covered_ids == requested_ids

    deliveries_by_id = {d["id"]: d for d in scenario["deliveries"]}
    for route in body["routes"]:
        sequences = [s["sequence"] for s in route["stops"]]
        assert sequences == list(range(len(sequences)))
        for stop in route["stops"]:
            assert stop["estimated_arrival"] is not None
            assert stop["estimated_departure"] is not None
            delivery = deliveries_by_id[stop["delivery_id"]]
            assert stop["latitude"] == delivery["latitude"]
            assert stop["longitude"] == delivery["longitude"]


def test_get_route_returns_stops_matching_optimize_response(scenario: dict, client: TestClient) -> None:
    payload = {
        "delivery_ids": [d["id"] for d in scenario["deliveries"]],
        "vehicle_ids": [v["id"] for v in scenario["vehicles"]],
        "depot_id": scenario["depot"]["id"],
        "return_to_depot": True,
    }
    optimize_response = client.post("/api/v1/routes/optimize", json=payload)
    assert optimize_response.status_code == 200
    routes = optimize_response.json()["routes"]
    assert routes

    route_id = routes[0]["id"]
    get_response = client.get(f"/api/v1/routes/{route_id}")
    assert get_response.status_code == 200

    fetched = get_response.json()
    assert fetched["id"] == route_id
    assert fetched["stops"] == routes[0]["stops"]


def test_get_route_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/routes/{uuid.uuid4()}")
    assert response.status_code == 404


def test_optimize_missing_depot_returns_422(scenario: dict, client: TestClient) -> None:
    payload = {
        "delivery_ids": [d["id"] for d in scenario["deliveries"]],
        "vehicle_ids": [v["id"] for v in scenario["vehicles"]],
        "depot_id": str(uuid.uuid4()),
        "return_to_depot": True,
    }
    response = client.post("/api/v1/routes/optimize", json=payload)
    assert response.status_code == 422


def test_return_to_depot_false_does_not_charge_return_leg(scenario: dict, client: TestClient) -> None:
    base_payload = {
        "delivery_ids": [d["id"] for d in scenario["deliveries"]],
        "vehicle_ids": [v["id"] for v in scenario["vehicles"]],
        "depot_id": scenario["depot"]["id"],
    }

    returning_response = client.post(
        "/api/v1/routes/optimize", json={**base_payload, "return_to_depot": True}
    )
    assert returning_response.status_code == 200
    returning_total = sum(r["total_distance_km"] for r in returning_response.json()["routes"])

    non_returning_response = client.post(
        "/api/v1/routes/optimize", json={**base_payload, "return_to_depot": False}
    )
    assert non_returning_response.status_code == 200
    non_returning_total = sum(r["total_distance_km"] for r in non_returning_response.json()["routes"])

    assert non_returning_total <= returning_total + 1e-6
