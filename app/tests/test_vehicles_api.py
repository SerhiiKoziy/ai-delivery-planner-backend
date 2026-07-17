"""Integration tests for the /api/v1/vehicles endpoints.

Uses the in-memory SQLite `client` fixture from conftest.py.
"""

import uuid

from fastapi.testclient import TestClient


def _make_payload(**overrides) -> dict:
    payload = {
        "plate_number": "AA1234BB",
    }
    payload.update(overrides)
    return payload


def test_create_vehicle_returns_expected_fields_and_defaults(client: TestClient) -> None:
    response = client.post("/api/v1/vehicles/", json=_make_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["plate_number"] == "AA1234BB"
    assert body["status"] == "active"
    assert body["capacity_weight_kg"] == 0.0
    assert body["capacity_volume_m3"] == 0.0
    assert body["driver_id"] is None
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_list_vehicles_returns_newest_first(client: TestClient) -> None:
    first = client.post("/api/v1/vehicles/", json=_make_payload(plate_number="First")).json()
    second = client.post("/api/v1/vehicles/", json=_make_payload(plate_number="Second")).json()

    response = client.get("/api/v1/vehicles/")
    assert response.status_code == 200

    body = response.json()
    assert len(body) == 2
    ids = [row["id"] for row in body]
    assert ids == [second["id"], first["id"]]


def test_get_vehicle_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/vehicles/", json=_make_payload()).json()

    response = client.get(f"/api/v1/vehicles/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_vehicle_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/vehicles/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_vehicle_changes_only_specified_field(client: TestClient) -> None:
    created = client.post("/api/v1/vehicles/", json=_make_payload()).json()

    response = client.put(
        f"/api/v1/vehicles/{created['id']}", json={"capacity_weight_kg": 1200.5}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["capacity_weight_kg"] == 1200.5
    assert body["plate_number"] == created["plate_number"]
    assert body["status"] == created["status"]
    assert body["capacity_volume_m3"] == created["capacity_volume_m3"]


def test_update_vehicle_not_found(client: TestClient) -> None:
    response = client.put(f"/api/v1/vehicles/{uuid.uuid4()}", json={"plate_number": "ZZ0000ZZ"})
    assert response.status_code == 404


def test_delete_vehicle(client: TestClient) -> None:
    created = client.post("/api/v1/vehicles/", json=_make_payload()).json()

    delete_response = client.delete(f"/api/v1/vehicles/{created['id']}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/vehicles/{created['id']}")
    assert get_response.status_code == 404


def test_delete_vehicle_not_found(client: TestClient) -> None:
    response = client.delete(f"/api/v1/vehicles/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_vehicle_with_assigned_driver(client: TestClient) -> None:
    driver = client.post(
        "/api/v1/drivers/", json={"name": "Carl Driver", "phone": "+380509998877"}
    ).json()

    response = client.post(
        "/api/v1/vehicles/", json=_make_payload(driver_id=driver["id"])
    )
    assert response.status_code == 200

    body = response.json()
    assert body["driver_id"] == driver["id"]
