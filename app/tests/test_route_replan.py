"""Tests for `RouteOptimizerService.replan()` (Phase 1 non-AI mechanics) and
the `PATCH /api/v1/routes/{route_id}/stops/{stop_id}` stop-status endpoint.

Follows the conventions in test_route_optimizer_api.py: the `client` fixture,
`mock_geocode`, and helper functions build a depot + drivers + vehicles +
geocoded deliveries via real HTTP calls, then `POST /api/v1/routes/optimize`
produces a real, persisted route to replan against.

`replan()` itself is exercised by instantiating `RouteOptimizerService`
directly against the same `db_session` the `client` fixture uses (mirroring
how `app.core.dependencies.get_route_optimizer_service` wires it up), since
there is no `/ai/replan` endpoint yet in this phase.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.geocoding.client import GoogleGeocodingClient
from app.services.route_optimizer.service import RouteOptimizerService

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
    """Pick the route with the most stops, to maximize room for exclusion tests."""
    return max(routes, key=lambda r: len(r["stops"]))


def _build_service(db_session: AsyncSession, organization_id) -> RouteOptimizerService:
    """Instantiate RouteOptimizerService directly, mirroring
    `get_route_optimizer_service`'s wiring, for tests that need to call
    `replan()` without an `/ai/replan` endpoint (not built until Phase 2).
    `organization_id` must match the org `scenario`'s data was created under
    (i.e. `test_organization`, since `scenario` builds via the `client`
    fixture which is authenticated as `test_user`)."""
    return RouteOptimizerService(
        DeliveryRepository(db_session, organization_id),
        VehicleRepository(db_session, organization_id),
        DriverRepository(db_session, organization_id),
        DepotRepository(db_session, organization_id),
        RouteRepository(db_session, organization_id),
        RouteStopRepository(db_session),
        db_session,
    )


# ---------------------------------------------------------------------------
# replan() service-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replan_no_changes_reproduces_equivalent_route(
    scenario: dict, client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    routes = _optimize(client, scenario)
    route = _largest_route(routes)
    stop_count_before = len(route["stops"])

    service = _build_service(db_session, test_organization.id)
    outcome = await service.replan(uuid.UUID(route["id"]))

    assert len(outcome.stops_before) == stop_count_before
    assert len(outcome.stops_after) == stop_count_before
    assert outcome.route.id == uuid.UUID(route["id"])


@pytest.mark.asyncio
async def test_replan_excludes_delivery_removes_it_from_pending_stops(
    scenario: dict, client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    routes = _optimize(client, scenario)
    route = _largest_route(routes)
    assert len(route["stops"]) >= 2, "need at least 2 stops for a meaningful partial exclusion"

    excluded_delivery_id = uuid.UUID(route["stops"][0]["delivery_id"])

    service = _build_service(db_session, test_organization.id)
    outcome = await service.replan(
        uuid.UUID(route["id"]), excluded_delivery_ids=[excluded_delivery_id]
    )

    stops_after_delivery_ids = {s.delivery_id for s in outcome.stops_after}
    assert excluded_delivery_id not in stops_after_delivery_ids
    assert len(outcome.stops_after) < len(outcome.stops_before)


@pytest.mark.asyncio
async def test_replan_dry_run_does_not_change_db(
    scenario: dict, client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    routes = _optimize(client, scenario)
    route = _largest_route(routes)
    route_id = uuid.UUID(route["id"])

    route_stop_repo = RouteStopRepository(db_session)
    stops_before = await route_stop_repo.list_by_route(route_id)
    before_snapshot = [
        (s.id, s.delivery_id, s.sequence, s.status, s.estimated_arrival, s.estimated_departure)
        for s in stops_before
    ]

    service = _build_service(db_session, test_organization.id)
    outcome = await service.replan(route_id, persist=False)

    # The dry run should still report a plausible simulated result...
    assert len(outcome.stops_after) == len(stops_before)

    # ...but the DB itself must be untouched.
    stops_after_dry_run = await route_stop_repo.list_by_route(route_id)
    after_snapshot = [
        (s.id, s.delivery_id, s.sequence, s.status, s.estimated_arrival, s.estimated_departure)
        for s in stops_after_dry_run
    ]
    assert after_snapshot == before_snapshot


@pytest.mark.asyncio
async def test_replan_excluding_all_remaining_pending_does_not_crash(
    scenario: dict, client: TestClient, db_session: AsyncSession, test_organization: Organization
) -> None:
    routes = _optimize(client, scenario)
    route = _largest_route(routes)
    all_delivery_ids = [uuid.UUID(s["delivery_id"]) for s in route["stops"]]

    service = _build_service(db_session, test_organization.id)
    outcome = await service.replan(
        uuid.UUID(route["id"]), excluded_delivery_ids=all_delivery_ids
    )

    # Every stop was pending and excluded -> nothing preserved, nothing re-optimized.
    assert outcome.stops_after == []
    assert outcome.unassigned_delivery_ids == []

    route_stop_repo = RouteStopRepository(db_session)
    remaining_stops = await route_stop_repo.list_by_route(uuid.UUID(route["id"]))
    assert remaining_stops == []


@pytest.mark.asyncio
async def test_replan_route_not_found_raises_value_error(
    db_session: AsyncSession, test_organization: Organization
) -> None:
    service = _build_service(db_session, test_organization.id)
    with pytest.raises(ValueError, match="Route not found"):
        await service.replan(uuid.uuid4())


# ---------------------------------------------------------------------------
# PATCH /api/v1/routes/{route_id}/stops/{stop_id}
# ---------------------------------------------------------------------------


def test_patch_stop_status_marks_completed_and_reflects_in_get_route(
    scenario: dict, client: TestClient
) -> None:
    routes = _optimize(client, scenario)
    route = _largest_route(routes)
    route_id = route["id"]
    stop_id = route["stops"][0]["id"]

    response = client.patch(
        f"/api/v1/routes/{route_id}/stops/{stop_id}", json={"status": "completed"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    get_response = client.get(f"/api/v1/routes/{route_id}")
    assert get_response.status_code == 200
    fetched_stop = next(s for s in get_response.json()["stops"] if s["id"] == stop_id)
    assert fetched_stop["status"] == "completed"


def test_patch_stop_status_unknown_stop_returns_404(scenario: dict, client: TestClient) -> None:
    routes = _optimize(client, scenario)
    route_id = routes[0]["id"]

    response = client.patch(
        f"/api/v1/routes/{route_id}/stops/{uuid.uuid4()}", json={"status": "completed"}
    )
    assert response.status_code == 404


def test_patch_stop_status_stop_from_other_route_returns_404(
    scenario: dict, client: TestClient
) -> None:
    routes = _optimize(client, scenario)
    assert len(routes) >= 1
    # Use a stop that belongs to a *different* route id than the one in the URL,
    # to confirm we don't leak stops across routes. If only one route was
    # produced, fabricate a route id that certainly doesn't own this stop.
    stop_id = routes[0]["stops"][0]["id"]
    other_route_id = routes[1]["id"] if len(routes) > 1 else str(uuid.uuid4())

    response = client.patch(
        f"/api/v1/routes/{other_route_id}/stops/{stop_id}", json={"status": "completed"}
    )
    assert response.status_code == 404
