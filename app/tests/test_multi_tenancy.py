"""Tenant-isolation tests: an organization must never be able to see or
mutate another organization's data through any endpoint.

Most tests seed "foreign" data directly via repositories (bound to
`other_organization`), bypassing HTTP entirely, then use the `client`
fixture (authenticated as `test_user` / `test_organization`) to attempt
access through the real API and assert it fails cleanly (404/422, never a
2xx, never a leaked row). One test (`test_real_registration_isolates_orgs`)
instead drives two full real-JWT sessions via `unauthenticated_client`, to
prove the isolation holds end-to-end through the actual register/login flow
too, not just against fixture-constructed users.
"""

import uuid
from datetime import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_email_verification_token

from app.db.models.organization import Organization
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.vehicle_repository import VehicleRepository


@pytest.fixture
async def other_org_depot(db_session: AsyncSession, other_organization: Organization):
    return await DepotRepository(db_session, other_organization.id).create(
        address="Lviv depot", latitude=49.8397, longitude=24.0297
    )


@pytest.fixture
async def other_org_driver(db_session: AsyncSession, other_organization: Organization):
    return await DriverRepository(db_session, other_organization.id).create(
        name="Foreign Driver", phone="+380671112233"
    )


@pytest.fixture
async def other_org_vehicle(db_session: AsyncSession, other_organization: Organization, other_org_driver):
    return await VehicleRepository(db_session, other_organization.id).create(
        plate_number="FF9999FF",
        capacity_weight_kg=300.0,
        capacity_volume_m3=3.0,
        driver_id=other_org_driver.id,
    )


@pytest.fixture
async def other_org_delivery(db_session: AsyncSession, other_organization: Organization):
    return await DeliveryRepository(db_session, other_organization.id).create(
        customer_name="Foreign Customer",
        address="Lviv, Foreign street",
        status="geocoded",
        latitude=49.84,
        longitude=24.03,
    )


@pytest.fixture
async def other_org_route_with_stop(
    db_session: AsyncSession, other_organization: Organization, other_org_depot, other_org_delivery
):
    route = await RouteRepository(db_session, other_organization.id).create(
        depot_id=other_org_depot.id,
        status="planned",
        return_to_depot=True,
        total_distance_km=9.0,
        total_duration_minutes=30,
    )
    stop = await RouteStopRepository(db_session).create(
        route_id=route.id,
        delivery_id=other_org_delivery.id,
        sequence=0,
        estimated_arrival=time(9, 0),
        estimated_departure=time(9, 10),
        distance_from_previous_km=9.0,
    )
    return route, stop


# ---------------------------------------------------------------------------
# GET/list are org-scoped
# ---------------------------------------------------------------------------


def test_delivery_list_and_get_are_org_scoped(client: TestClient, other_org_delivery) -> None:
    own = client.post(
        "/api/v1/deliveries/",
        json={"customer_name": "Own Customer", "address": "Kyiv, Own street"},
    )
    assert own.status_code == 200
    own_id = own.json()["id"]

    listed = client.get("/api/v1/deliveries/")
    assert listed.status_code == 200
    listed_ids = {d["id"] for d in listed.json()}
    assert listed_ids == {own_id}, "another organization's delivery leaked into the list"

    get_foreign = client.get(f"/api/v1/deliveries/{other_org_delivery.id}")
    assert get_foreign.status_code == 404


def test_depot_list_and_get_are_org_scoped(client: TestClient, other_org_depot) -> None:
    own = client.post(
        "/api/v1/depots/", json={"address": "Kyiv depot", "latitude": 50.45, "longitude": 30.52}
    )
    assert own.status_code == 200

    listed = client.get("/api/v1/depots/")
    listed_ids = {d["id"] for d in listed.json()}
    assert str(other_org_depot.id) not in listed_ids

    assert client.get(f"/api/v1/depots/{other_org_depot.id}").status_code == 404


def test_driver_list_and_get_are_org_scoped(client: TestClient, other_org_driver) -> None:
    own = client.post("/api/v1/drivers/", json={"name": "Own Driver", "phone": "+380501112233"})
    assert own.status_code == 200

    listed = client.get("/api/v1/drivers/")
    listed_ids = {d["id"] for d in listed.json()}
    assert str(other_org_driver.id) not in listed_ids

    assert client.get(f"/api/v1/drivers/{other_org_driver.id}").status_code == 404


def test_vehicle_list_and_get_are_org_scoped(client: TestClient, other_org_vehicle) -> None:
    own = client.post(
        "/api/v1/vehicles/",
        json={"plate_number": "AA1111AA", "capacity_weight_kg": 500.0, "capacity_volume_m3": 5.0},
    )
    assert own.status_code == 200

    listed = client.get("/api/v1/vehicles/")
    listed_ids = {v["id"] for v in listed.json()}
    assert str(other_org_vehicle.id) not in listed_ids

    assert client.get(f"/api/v1/vehicles/{other_org_vehicle.id}").status_code == 404


def test_route_get_is_org_scoped(client: TestClient, other_org_route_with_stop) -> None:
    route, _stop = other_org_route_with_stop
    assert client.get(f"/api/v1/routes/{route.id}").status_code == 404


# ---------------------------------------------------------------------------
# UPDATE/DELETE never touch another organization's row
# ---------------------------------------------------------------------------


async def test_update_and_delete_are_org_scoped(
    client: TestClient, other_org_delivery, db_session: AsyncSession, other_organization: Organization
) -> None:
    put_response = client.put(
        f"/api/v1/deliveries/{other_org_delivery.id}", json={"customer_name": "Hijacked"}
    )
    assert put_response.status_code == 404

    delete_response = client.delete(f"/api/v1/deliveries/{other_org_delivery.id}")
    assert delete_response.status_code == 404

    # The foreign row must be completely untouched.
    untouched = await DeliveryRepository(db_session, other_organization.id).get(
        other_org_delivery.id
    )
    assert untouched is not None
    assert untouched.customer_name == "Foreign Customer"


def test_patch_stop_status_requires_route_ownership(
    client: TestClient, other_org_route_with_stop
) -> None:
    route, stop = other_org_route_with_stop
    response = client.patch(
        f"/api/v1/routes/{route.id}/stops/{stop.id}", json={"status": "completed"}
    )
    assert response.status_code == 404


def test_chat_history_requires_route_ownership(
    client: TestClient, other_org_route_with_stop
) -> None:
    route, _stop = other_org_route_with_stop
    response = client.get(f"/api/v1/ai/chat/{route.id}/history")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cross-org ids never get used, just silently excluded
# ---------------------------------------------------------------------------


def test_optimize_ignores_cross_org_depot(client: TestClient, other_org_depot) -> None:
    delivery = client.post(
        "/api/v1/deliveries/",
        json={"customer_name": "Own Customer", "address": "Kyiv, Own street"},
    ).json()
    vehicle = client.post(
        "/api/v1/vehicles/",
        json={"plate_number": "BB2222BB", "capacity_weight_kg": 500.0, "capacity_volume_m3": 5.0},
    ).json()

    response = client.post(
        "/api/v1/routes/optimize",
        json={
            "delivery_ids": [delivery["id"]],
            "vehicle_ids": [vehicle["id"]],
            "depot_id": str(other_org_depot.id),
        },
    )
    # The depot "doesn't exist" from this org's point of view.
    assert response.status_code == 422


def test_optimize_silently_drops_cross_org_delivery(
    client: TestClient, other_org_delivery
) -> None:
    depot = client.post(
        "/api/v1/depots/", json={"address": "Kyiv depot", "latitude": 50.45, "longitude": 30.52}
    ).json()
    driver = client.post(
        "/api/v1/drivers/", json={"name": "Own Driver", "phone": "+380501112233"}
    ).json()
    vehicle = client.post(
        "/api/v1/vehicles/",
        json={
            "plate_number": "CC3333CC",
            "capacity_weight_kg": 500.0,
            "capacity_volume_m3": 5.0,
            "driver_id": driver["id"],
        },
    ).json()

    response = client.post(
        "/api/v1/routes/optimize",
        json={
            "delivery_ids": [str(other_org_delivery.id)],
            "vehicle_ids": [vehicle["id"]],
            "depot_id": depot["id"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    # The foreign delivery id must not surface anywhere in the response —
    # not routed, not unassigned, not even flagged as un-geocoded. It's
    # treated exactly as if it never existed.
    assert body["routes"] == []
    assert str(other_org_delivery.id) not in {d["id"] for d in body["unassigned_deliveries"]}
    assert str(other_org_delivery.id) not in {d["id"] for d in body["skipped_not_geocoded"]}


def test_vehicle_cannot_link_to_foreign_driver(client: TestClient, other_org_driver) -> None:
    response = client.post(
        "/api/v1/vehicles/",
        json={
            "plate_number": "DD4444DD",
            "capacity_weight_kg": 500.0,
            "capacity_volume_m3": 5.0,
            "driver_id": str(other_org_driver.id),
        },
    )
    assert response.status_code == 422


def test_vehicle_update_cannot_link_to_foreign_driver(
    client: TestClient, other_org_driver
) -> None:
    vehicle = client.post(
        "/api/v1/vehicles/",
        json={"plate_number": "EE5555EE", "capacity_weight_kg": 500.0, "capacity_volume_m3": 5.0},
    ).json()

    response = client.put(
        f"/api/v1/vehicles/{vehicle['id']}", json={"driver_id": str(other_org_driver.id)}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Dashboard aggregates are per-organization
# ---------------------------------------------------------------------------


def test_dashboard_overview_is_per_organization(
    client: TestClient, other_org_route_with_stop, other_org_delivery
) -> None:
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    # test_user's org has created nothing yet — the other org's route/
    # delivery must not leak into these aggregates.
    assert body == {
        "deliveriesToday": 0,
        "activeDrivers": 0,
        "totalDistanceKm": 0.0,
        "lateDeliveries": 0,
        "activeVehicles": 0,
        "driversOnRouteToday": 0,
        "driversIdleToday": 0,
        "vehiclesInUseToday": 0,
        "vehiclesAvailableToday": 0,
    }


# ---------------------------------------------------------------------------
# Realistic end-to-end check: two real registered users, real JWTs
# ---------------------------------------------------------------------------


def _register_and_verify(client: TestClient, email: str, password: str) -> dict:
    """Register a new account and immediately redeem its verification token,
    mirroring what a real user does after clicking the emailed link."""
    register_body = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    ).json()
    verify_token = create_email_verification_token(register_body["user_id"])
    return client.post("/api/v1/auth/verify-email", json={"token": verify_token}).json()


def test_real_registration_isolates_orgs(unauthenticated_client: TestClient) -> None:
    user_a = _register_and_verify(unauthenticated_client, "org.a@example.com", "password-123")
    user_b = _register_and_verify(unauthenticated_client, "org.b@example.com", "password-123")

    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    depot_a = unauthenticated_client.post(
        "/api/v1/depots/",
        json={"address": "A's depot", "latitude": 50.45, "longitude": 30.52},
        headers=headers_a,
    )
    assert depot_a.status_code == 200
    depot_a_id = depot_a.json()["id"]

    # B's list must not include A's depot...
    listed_by_b = unauthenticated_client.get("/api/v1/depots/", headers=headers_b)
    assert listed_by_b.status_code == 200
    assert listed_by_b.json() == []

    # ...and B can't fetch it directly by id either.
    get_by_b = unauthenticated_client.get(f"/api/v1/depots/{depot_a_id}", headers=headers_b)
    assert get_by_b.status_code == 404

    # A can still see their own depot.
    listed_by_a = unauthenticated_client.get("/api/v1/depots/", headers=headers_a)
    assert [d["id"] for d in listed_by_a.json()] == [depot_a_id]
