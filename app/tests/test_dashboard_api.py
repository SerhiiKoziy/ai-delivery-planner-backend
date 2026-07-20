"""Integration tests for GET /api/v1/dashboard/overview."""

import datetime as datetime_module

import pytest
from fastapi.testclient import TestClient

from app.services.dashboard import service as dashboard_service_module


class _FixedClock:
    """Stands in for `datetime` in the dashboard service so the "is this stop
    late" comparison always resolves against a fixed, late-in-the-day time
    (23:59) instead of the real wall clock — otherwise this test would be
    flaky depending on what time of day it happens to run.
    """

    @staticmethod
    def now(tz=None):
        # UTC date, not the local `date.today()` — `created_at` timestamps
        # in this schema are always stored via `datetime.now(UTC)`, so the
        # fixed clock must agree with that basis or this test itself becomes
        # flaky near midnight UTC on machines with a local timezone ahead of
        # UTC (exactly the bug this fixed clock exists to paper over for the
        # real service, just one level up).
        today_utc = datetime_module.datetime.now(datetime_module.UTC).date()
        return datetime_module.datetime.combine(today_utc, datetime_module.time(23, 59), tzinfo=tz)


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_service_module, "datetime", _FixedClock)


def test_overview_reflects_current_state(
    client: TestClient, route_with_stops: dict, fixed_clock: None
) -> None:
    driver_response = client.post(
        "/api/v1/drivers/", json={"name": "Active Driver", "phone": "+380501112233"}
    )
    assert driver_response.status_code == 200

    inactive_driver_response = client.post(
        "/api/v1/drivers/",
        json={"name": "Inactive Driver", "phone": "+380509998877", "status": "inactive"},
    )
    assert inactive_driver_response.status_code == 200

    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200

    body = response.json()
    assert body == {
        "deliveriesToday": 1,
        "activeDrivers": 1,
        "totalDistanceKm": 12.5,
        "lateDeliveries": 1,
        "activeVehicles": 0,
        "driversOnRouteToday": 0,
        "driversIdleToday": 1,
        "vehiclesInUseToday": 0,
        "vehiclesAvailableToday": 0,
    }


def test_overview_with_no_data(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    assert response.json() == {
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


def test_usage_history_zero_filled_with_no_data(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/usage-history")
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 30
    assert all(
        p["deliveriesCount"] == 0 and p["routesGenerated"] == 0 and p["distanceKm"] == 0.0
        for p in points
    )
    # Dates are contiguous and end on today (UTC).
    dates = [datetime_module.date.fromisoformat(p["date"]) for p in points]
    assert dates == sorted(dates)
    assert dates[-1] == datetime_module.datetime.now(datetime_module.UTC).date()


def test_usage_history_reflects_todays_activity(
    client: TestClient, route_with_stops: dict
) -> None:
    response = client.get("/api/v1/dashboard/usage-history?days=7")
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 7

    today = datetime_module.datetime.now(datetime_module.UTC).date().isoformat()
    today_point = next(p for p in points if p["date"] == today)
    assert today_point == {
        "date": today,
        "deliveriesCount": 1,
        "routesGenerated": 1,
        "distanceKm": 12.5,
    }
