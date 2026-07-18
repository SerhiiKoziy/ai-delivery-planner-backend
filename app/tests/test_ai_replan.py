"""Integration tests for POST /api/v1/ai/replan.

Follows the conventions in test_route_replan.py and test_ai_explain.py: the
`ai_client` fixture (fake OpenAI client via `mock_openai_client`, no network)
sits on top of the standard authenticated `client` fixture, and a real
depot/drivers/vehicles/deliveries scenario is built via `POST
/api/v1/routes/optimize` so there is a real, persisted route to replan
against. `mock_openai_client.replan_interpretation` is set per-test to control
what the fake "understood" from the dispatcher message, since the fake can't
actually parse free text like a real model would.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.services.geocoding.client import GoogleGeocodingClient
from app.tests.conftest import FakeOpenAIClient

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


def _optimize(client: TestClient, scenario: dict) -> list[dict]:
    payload = {
        "delivery_ids": [d["id"] for d in scenario["deliveries"]],
        "vehicle_ids": [v["id"] for v in scenario["vehicles"]],
        "depot_id": scenario["depot"]["id"],
        "return_to_depot": True,
    }
    response = client.post("/api/v1/routes/optimize", json=payload)
    assert response.status_code == 200
    routes = response.json()["routes"]
    assert routes
    return routes


def _largest_route(routes: list[dict]) -> dict:
    """Pick the route with the most stops, to maximize room for diff assertions."""
    return max(routes, key=lambda r: len(r["stops"]))


def test_replan_customer_unreachable_removes_stop_and_makes_two_ai_calls(
    ai_client: TestClient, scenario: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    routes = _optimize(ai_client, scenario)
    route = _largest_route(routes)
    assert len(route["stops"]) >= 2, "need at least 2 stops for a meaningful exclusion"

    target_stop = route["stops"][0]
    target_delivery_id = target_stop["delivery_id"]

    mock_openai_client.replan_interpretation = {
        "event_type": "customer_unreachable",
        "affected_stop_sequence": target_stop["sequence"],
        "new_window_start": None,
        "new_window_end": None,
        "delay_minutes": None,
        "summary": "Customer at that stop is not answering the phone.",
    }

    response = ai_client.post(
        "/api/v1/ai/replan",
        json={
            "route_id": route["id"],
            "message": "Клієнт не відповідає на дзвінки",
            "dry_run": False,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["applied"] is True
    assert body["interpretation"]["event_type"] == "customer_unreachable"

    removed_entries = [d for d in body["diff"] if d["delivery_id"] == target_delivery_id]
    assert len(removed_entries) == 1
    assert removed_entries[0]["change"] == "removed"

    # Exactly 2 OpenAI calls: one to interpret, one to explain the diff.
    assert len(mock_openai_client.calls) == 2

    # The excluded delivery should indeed be gone from the persisted route.
    get_response = ai_client.get(f"/api/v1/routes/{route['id']}")
    assert get_response.status_code == 200
    remaining_delivery_ids = {s["delivery_id"] for s in get_response.json()["stops"]}
    assert target_delivery_id not in remaining_delivery_ids


def test_replan_unrecognized_message_makes_one_ai_call_and_applies_nothing(
    ai_client: TestClient, scenario: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    routes = _optimize(ai_client, scenario)
    route = _largest_route(routes)

    # An event type that needs a stop, but with a sequence that doesn't exist
    # among the route's pending stops -> interpret_replan_message() must
    # defensively downgrade this to "unrecognized" itself.
    mock_openai_client.replan_interpretation = {
        "event_type": "customer_unreachable",
        "affected_stop_sequence": 9999,
        "new_window_start": None,
        "new_window_end": None,
        "delay_minutes": None,
        "summary": "Some ambiguous message.",
    }

    response = ai_client.post(
        "/api/v1/ai/replan",
        json={
            "route_id": route["id"],
            "message": "щось незрозуміле",
            "dry_run": False,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["applied"] is False
    assert body["diff"] == []
    assert body["interpretation"]["event_type"] == "unrecognized"
    assert body["total_distance_km_before"] == body["total_distance_km_after"]
    assert body["total_duration_minutes_before"] == body["total_duration_minutes_after"]
    assert body["time_saved_minutes"] == 0.0

    # Only the interpretation call was made -- no explain_replan() call wasted
    # on an unrecognized message.
    assert len(mock_openai_client.calls) == 1

    # Nothing should have been persisted.
    get_response = ai_client.get(f"/api/v1/routes/{route['id']}")
    assert get_response.status_code == 200
    original_stop_ids = {s["id"] for s in route["stops"]}
    fetched_stop_ids = {s["id"] for s in get_response.json()["stops"]}
    assert fetched_stop_ids == original_stop_ids


def test_replan_dry_run_computes_diff_without_persisting(
    ai_client: TestClient, scenario: dict, mock_openai_client: FakeOpenAIClient
) -> None:
    routes = _optimize(ai_client, scenario)
    route = _largest_route(routes)
    assert len(route["stops"]) >= 2

    before_response = ai_client.get(f"/api/v1/routes/{route['id']}")
    assert before_response.status_code == 200
    before_stops = before_response.json()["stops"]

    target_stop = route["stops"][0]
    target_delivery_id = target_stop["delivery_id"]

    mock_openai_client.replan_interpretation = {
        "event_type": "delivery_cancelled",
        "affected_stop_sequence": target_stop["sequence"],
        "new_window_start": None,
        "new_window_end": None,
        "delay_minutes": None,
        "summary": "Customer cancelled this delivery.",
    }

    response = ai_client.post(
        "/api/v1/ai/replan",
        json={
            "route_id": route["id"],
            "message": "Клієнт скасував доставку",
            "dry_run": True,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["applied"] is True
    removed_entries = [d for d in body["diff"] if d["delivery_id"] == target_delivery_id]
    assert len(removed_entries) == 1
    assert removed_entries[0]["change"] == "removed"

    # But nothing was actually persisted: re-fetching the route shows the
    # exact same stops as before the dry-run call.
    after_response = ai_client.get(f"/api/v1/routes/{route['id']}")
    assert after_response.status_code == 200
    after_stops = after_response.json()["stops"]
    assert after_stops == before_stops


def test_replan_404s_for_unknown_route(ai_client: TestClient) -> None:
    response = ai_client.post(
        "/api/v1/ai/replan",
        json={"route_id": str(uuid.uuid4()), "message": "hello", "dry_run": False},
    )
    assert response.status_code == 404
