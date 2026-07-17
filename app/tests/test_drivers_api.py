"""Integration tests for the /api/v1/drivers endpoints.

Uses the in-memory SQLite `client` fixture from conftest.py.
"""

import uuid

from fastapi.testclient import TestClient


def _make_payload(**overrides) -> dict:
    payload = {
        "name": "Alice Driver",
        "phone": "+380501112233",
    }
    payload.update(overrides)
    return payload


def test_create_driver_returns_expected_fields_and_defaults(client: TestClient) -> None:
    response = client.post("/api/v1/drivers/", json=_make_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Alice Driver"
    assert body["phone"] == "+380501112233"
    assert body["status"] == "active"
    assert body["working_hours_start"] == "08:00:00"
    assert body["working_hours_end"] == "18:00:00"
    assert body["break_start"] == "13:00:00"
    assert body["break_end"] == "14:00:00"
    assert body["max_working_minutes"] == 600
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_list_drivers_returns_newest_first(client: TestClient) -> None:
    first = client.post("/api/v1/drivers/", json=_make_payload(name="First")).json()
    second = client.post("/api/v1/drivers/", json=_make_payload(name="Second")).json()

    response = client.get("/api/v1/drivers/")
    assert response.status_code == 200

    body = response.json()
    assert len(body) == 2
    ids = [row["id"] for row in body]
    assert ids == [second["id"], first["id"]]


def test_get_driver_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/drivers/", json=_make_payload()).json()

    response = client.get(f"/api/v1/drivers/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_driver_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/drivers/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_driver_changes_only_specified_field(client: TestClient) -> None:
    created = client.post("/api/v1/drivers/", json=_make_payload()).json()

    response = client.put(f"/api/v1/drivers/{created['id']}", json={"name": "Bob Driver"})
    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Bob Driver"
    assert body["phone"] == created["phone"]
    assert body["status"] == created["status"]
    assert body["max_working_minutes"] == created["max_working_minutes"]


def test_update_driver_not_found(client: TestClient) -> None:
    response = client.put(f"/api/v1/drivers/{uuid.uuid4()}", json={"name": "Nobody"})
    assert response.status_code == 404


def test_delete_driver(client: TestClient) -> None:
    created = client.post("/api/v1/drivers/", json=_make_payload()).json()

    delete_response = client.delete(f"/api/v1/drivers/{created['id']}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/drivers/{created['id']}")
    assert get_response.status_code == 404


def test_delete_driver_not_found(client: TestClient) -> None:
    response = client.delete(f"/api/v1/drivers/{uuid.uuid4()}")
    assert response.status_code == 404
