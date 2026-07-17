"""Integration tests for the /api/v1/depots endpoints.

Uses the in-memory SQLite `client` fixture from conftest.py.
"""

import uuid

from fastapi.testclient import TestClient


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
