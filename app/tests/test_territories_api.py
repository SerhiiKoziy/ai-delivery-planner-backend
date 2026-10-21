"""Integration tests for territory planning and the quantum-run log:
POST/GET /api/v1/territories/plans, GET /api/v1/quantum/{runs,summary},
and POST /api/v1/routes/optimize with a territory_plan_id.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.repositories.quantum_run_repository import QuantumRunRepository
from app.repositories.territory_plan_repository import TerritoryPlanRepository
from app.services.geocoding.client import GoogleGeocodingClient
from app.services.territory.providers import NumpyStatevectorProvider, qiskit_available

DEPOT_LAT, DEPOT_LNG = 50.4501, 30.5234

# Two neighbourhoods ~6 km apart, 4 stops each.
WEST = [(50.450, 30.450), (50.452, 30.452), (50.448, 30.453), (50.451, 30.447)]
EAST = [(50.450, 30.540), (50.453, 30.542), (50.447, 30.538), (50.450, 30.545)]
COORDINATES = WEST + EAST


@pytest.fixture
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GoogleGeocodingClient, "geocode", AsyncMock(side_effect=list(COORDINATES)))


@pytest.fixture
def scenario(client: TestClient, mock_geocode: None) -> dict:
    depot = client.post(
        "/api/v1/depots/",
        json={"address": "Kyiv depot", "latitude": DEPOT_LAT, "longitude": DEPOT_LNG},
    ).json()
    vehicles = []
    for i in range(4):
        driver = client.post(
            "/api/v1/drivers/", json={"name": f"Driver {i}", "phone": "+380501112233"}
        ).json()
        vehicles.append(
            client.post(
                "/api/v1/vehicles/",
                json={
                    "plate_number": f"AA{i}{i}{i}{i}AA",
                    "capacity_weight_kg": 500.0,
                    "capacity_volume_m3": 5.0,
                    "driver_id": driver["id"],
                },
            ).json()
        )
    deliveries = [
        client.post(
            "/api/v1/deliveries/",
            json={
                "customer_name": f"Customer {i}",
                "address": f"Kyiv, street {i}",
                "weight_kg": 5.0,
                "volume_m3": 0.1,
                "unloading_minutes": 5,
            },
        ).json()
        for i in range(len(COORDINATES))
    ]
    return {"depot": depot, "vehicles": vehicles, "deliveries": deliveries}


def _plan(client: TestClient, scenario: dict, solver: str, zones: int = 2, **extra):
    return client.post(
        "/api/v1/territories/plans",
        json={
            "delivery_ids": [d["id"] for d in scenario["deliveries"]],
            "vehicle_ids": [v["id"] for v in scenario["vehicles"][:zones]],
            "solver": solver,
            **extra,
        },
    )


def _zone_sets(plan: dict) -> list[set[str]]:
    return [set(z["delivery_ids"]) for z in plan["zones"]]


def test_classical_plan_splits_neighbourhoods_without_quantum_runs(
    client: TestClient, scenario: dict
) -> None:
    response = _plan(client, scenario, "classical")
    assert response.status_code == 200
    plan = response.json()

    ids = [d["id"] for d in scenario["deliveries"]]
    assert plan["status"] == "completed"
    assert sorted(_zone_sets(plan), key=len) and {frozenset(s) for s in _zone_sets(plan)} == {
        frozenset(ids[:4]),
        frozenset(ids[4:]),
    }
    assert [z["vehicle_id"] for z in plan["zones"]] == [v["id"] for v in scenario["vehicles"][:2]]
    assert plan["metrics"]["imbalance"] == pytest.approx(1.0)
    assert client.get("/api/v1/quantum/runs").json() == []


def test_quantum_simulator_plan_logs_every_quantum_interaction(
    client: TestClient, scenario: dict
) -> None:
    response = _plan(client, scenario, "quantum_simulator", qaoa_reps=2, shots=1024)
    assert response.status_code == 200
    plan = response.json()
    ids = [d["id"] for d in scenario["deliveries"]]
    assert {frozenset(s) for s in _zone_sets(plan)} == {frozenset(ids[:4]), frozenset(ids[4:])}
    assert plan["metrics"]["quantum_runs"] == 1

    runs = client.get("/api/v1/quantum/runs", params={"territory_plan_id": plan["id"]}).json()
    assert len(runs) == 1
    run = runs[0]
    assert run["provider"] == "numpy_statevector"
    assert run["status"] == "completed"
    assert run["step"] == "root"
    assert run["num_qubits"] == 8
    assert run["qaoa_reps"] == 2
    assert run["shots"] == 1024
    for field in ("build_ms", "classical_ms", "optimize_ms", "execution_ms", "total_ms"):
        assert run[field] is not None and run[field] >= 0
    assert 0 < run["approximation_ratio"] <= 1
    assert run["optimizer_evaluations"] > 0
    assert run["submitted_at"] is not None and run["completed_at"] is not None
    assert run["chosen_source"] in {"quantum", "classical"}

    detail = client.get(f"/api/v1/quantum/runs/{run['id']}").json()
    assert len(detail["details"]["gammas"]) == 2
    assert sum(row["count"] for row in detail["details"]["top_counts"]) <= 1024
    assert detail["details"]["uniform_optimum_probability"] < run["optimum_probability"]

    summary = client.get("/api/v1/quantum/summary").json()
    assert summary["total_runs"] == 1
    assert summary["runs_by_status"] == {"completed": 1}
    assert summary["timings"]["total_ms"]["count"] == 1
    assert summary["solvers"]["quantum_simulator"]["available"] is True
    assert summary["total_shots"] == 1024


def test_four_zones_take_three_bisection_steps(client: TestClient, scenario: dict) -> None:
    plan = _plan(client, scenario, "quantum_simulator", zones=4, shots=512).json()
    assert plan["status"] == "completed"
    assert sum(z["stop_count"] for z in plan["zones"]) == 8
    assert all(z["stop_count"] == 2 for z in plan["zones"])
    steps = sorted(r["step"] for r in client.get("/api/v1/quantum/runs").json())
    assert steps == ["A", "B", "root"]


def test_backend_failure_falls_back_to_classical_and_is_logged(
    client: TestClient, scenario: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self, prepared):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(NumpyStatevectorProvider, "submit", boom)
    plan = _plan(client, scenario, "quantum_simulator").json()
    assert plan["status"] == "completed"
    assert len(plan["zones"]) == 2

    run = client.get("/api/v1/quantum/runs").json()[0]
    assert run["status"] == "failed"
    assert "backend exploded" in run["error"]
    assert run["chosen_source"] == "classical"


def test_real_qpu_without_token_is_rejected(client: TestClient, scenario: dict) -> None:
    response = _plan(client, scenario, "ibm_quantum")
    assert response.status_code == 422
    assert "IBM_QUANTUM_TOKEN" in response.json()["detail"]


@pytest.mark.skipif(not qiskit_available(), reason="quantum extra not installed")
def test_ibm_emulator_records_transpiled_circuit_and_job(
    client: TestClient, scenario: dict
) -> None:
    plan = _plan(client, scenario, "ibm_emulator", qaoa_reps=1, shots=512).json()
    assert plan["status"] == "completed"
    run = client.get("/api/v1/quantum/runs").json()[0]
    assert run["status"] == "completed"
    assert run["provider"] == "ibm_emulator"
    assert run["backend_name"] == "fake_brisbane"
    assert run["job_id"]
    assert run["transpiled_depth"] >= run["logical_depth"]
    assert run["transpiled_two_qubit_gates"] > 0
    assert run["transpile_ms"] > 0


def test_optimize_keeps_each_delivery_on_its_zone_vehicle(
    client: TestClient, scenario: dict
) -> None:
    plan = _plan(client, scenario, "quantum_simulator").json()
    zone_vehicle = {did: z["vehicle_id"] for z in plan["zones"] for did in z["delivery_ids"]}

    response = client.post(
        "/api/v1/routes/optimize",
        json={
            "delivery_ids": [d["id"] for d in scenario["deliveries"]],
            "vehicle_ids": [v["id"] for v in scenario["vehicles"][:2]],
            "depot_id": scenario["depot"]["id"],
            "territory_plan_id": plan["id"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    served = 0
    for route in body["routes"]:
        for stop in route["stops"]:
            assert zone_vehicle[stop["delivery_id"]] == route["vehicle_id"]
            served += 1
    assert served == 8


def test_optimize_rejects_unknown_territory_plan(client: TestClient, scenario: dict) -> None:
    response = client.post(
        "/api/v1/routes/optimize",
        json={
            "delivery_ids": [d["id"] for d in scenario["deliveries"]],
            "vehicle_ids": [v["id"] for v in scenario["vehicles"][:2]],
            "depot_id": scenario["depot"]["id"],
            "territory_plan_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 422


async def test_quantum_runs_are_tenant_scoped(
    client: TestClient, db_session, other_organization
) -> None:
    other_plan = await TerritoryPlanRepository(db_session, other_organization.id).create(
        status="completed",
        solver="quantum_simulator",
        balance_by="stops",
        num_zones=2,
        zones=[],
        metrics={},
    )
    other_run = await QuantumRunRepository(db_session, other_organization.id).create(
        territory_plan_id=other_plan.id,
        step="root",
        provider="numpy_statevector",
        status="completed",
        num_qubits=4,
        qaoa_reps=1,
        shots=100,
        details={},
    )
    assert client.get("/api/v1/quantum/runs").json() == []
    assert client.get(f"/api/v1/quantum/runs/{other_run.id}").status_code == 404
    assert client.get(f"/api/v1/territories/plans/{other_plan.id}").status_code == 404
    assert client.get("/api/v1/quantum/summary").json()["total_runs"] == 0


async def test_zone_constraint_overrides_the_cheapest_assignment(
    client: TestClient, scenario: dict, db_session, test_organization
) -> None:
    """Zones that interleave the two neighbourhoods are far from optimal for
    distance — the optimizer must obey them anyway."""
    ids = [d["id"] for d in scenario["deliveries"]]
    vehicles = scenario["vehicles"][:2]
    interleaved = [ids[0::2], ids[1::2]]
    plan = await TerritoryPlanRepository(db_session, test_organization.id).create(
        status="completed",
        solver="classical",
        balance_by="stops",
        num_zones=2,
        zones=[
            {"index": i, "vehicle_id": vehicles[i]["id"], "delivery_ids": zone}
            for i, zone in enumerate(interleaved)
        ],
        metrics={},
    )
    response = client.post(
        "/api/v1/routes/optimize",
        json={
            "delivery_ids": ids,
            "vehicle_ids": [v["id"] for v in vehicles],
            "depot_id": scenario["depot"]["id"],
            "territory_plan_id": str(plan.id),
        },
    )
    assert response.status_code == 200
    by_vehicle = {
        r["vehicle_id"]: {s["delivery_id"] for s in r["stops"]} for r in response.json()["routes"]
    }
    assert by_vehicle == {
        vehicles[0]["id"]: set(interleaved[0]),
        vehicles[1]["id"]: set(interleaved[1]),
    }


def test_quantum_lab_page_is_served(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/quantum-lab")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/quantum/summary" in response.text


def test_quantum_api_requires_auth(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/api/v1/quantum/runs").status_code == 401
    assert unauthenticated_client.get("/api/v1/quantum/summary").status_code == 401
