"""Integration tests for the /api/v1/deliveries endpoints.

Uses the in-memory SQLite `client` fixture from conftest.py. The Google
Geocoding HTTP call is monkeypatched so tests never touch the network.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.services.geocoding.client import GoogleGeocodingClient

MOCKED_LAT = 50.45
MOCKED_LNG = 30.52


@pytest.fixture(autouse=True)
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GoogleGeocodingClient, "geocode", AsyncMock(return_value=(MOCKED_LAT, MOCKED_LNG))
    )


def _make_payload(**overrides) -> dict:
    payload = {
        "customer_name": "John Smith",
        "address": "Kyiv, Khreshchatyk 10",
        "phone": "+380501112233",
    }
    payload.update(overrides)
    return payload


def test_create_delivery_geocodes_address(client: TestClient) -> None:
    response = client.post("/api/v1/deliveries/", json=_make_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "geocoded"
    assert body["latitude"] == MOCKED_LAT
    assert body["longitude"] == MOCKED_LNG
    assert body["customer_name"] == "John Smith"


def test_list_deliveries_returns_newest_first(client: TestClient) -> None:
    first = client.post("/api/v1/deliveries/", json=_make_payload(customer_name="First")).json()
    second = client.post("/api/v1/deliveries/", json=_make_payload(customer_name="Second")).json()

    response = client.get("/api/v1/deliveries/")
    assert response.status_code == 200

    body = response.json()
    assert len(body) == 2
    ids = [row["id"] for row in body]
    assert ids == [second["id"], first["id"]]


def test_get_delivery_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/deliveries/", json=_make_payload()).json()

    response = client.get(f"/api/v1/deliveries/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_delivery_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/deliveries/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_delivery_changes_only_specified_field(client: TestClient) -> None:
    created = client.post("/api/v1/deliveries/", json=_make_payload()).json()

    response = client.put(
        f"/api/v1/deliveries/{created['id']}", json={"customer_name": "Jane Doe"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["customer_name"] == "Jane Doe"
    assert body["address"] == created["address"]
    assert body["phone"] == created["phone"]
    assert body["latitude"] == created["latitude"]
    assert body["status"] == created["status"]


def test_delete_delivery(client: TestClient) -> None:
    created = client.post("/api/v1/deliveries/", json=_make_payload()).json()

    delete_response = client.delete(f"/api/v1/deliveries/{created['id']}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/deliveries/{created['id']}")
    assert get_response.status_code == 404


def test_import_csv_partial_success(client: TestClient) -> None:
    csv_bytes = (
        b"Customer Name,Address,Priority\n"
        b"John Smith,Kyiv Khreshchatyk 10,HIGH\n"
        b"Bad Row,,LOW\n"
    )

    response = client.post(
        "/api/v1/deliveries/import",
        files={"file": ("test.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["total_rows"] == 2
    assert body["imported"] == 1
    assert body["failed"] == 1

    failed_rows = [row for row in body["rows"] if not row["success"]]
    assert len(failed_rows) == 1
    assert failed_rows[0]["error"]

    succeeded_rows = [row for row in body["rows"] if row["success"]]
    assert len(succeeded_rows) == 1
    assert succeeded_rows[0]["delivery"]["status"] == "geocoded"
