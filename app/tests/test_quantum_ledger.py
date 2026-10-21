"""Tests for app.quantum_ledger — the durable record of IBM jobs: what was
sent, what came back, and the CPU reference for the same circuit."""

import ast
import pathlib
import warnings

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.quantum_ledger import QuantumLedger, compare, ising_problem_from_arrays
from app.quantum_ledger.analysis import hellinger_fidelity, ising_costs, total_variation_distance
from app.services.territory.problem import Point, aggregate, build_bisection_ising, ising_energies
from app.services.territory.providers import (
    IbmRuntimeProvider,
    QuantumTimeoutError,
    qiskit_available,
)
from app.tests.test_territories_api import _plan, mock_geocode, scenario  # noqa: F401

needs_qiskit = pytest.mark.skipif(not qiskit_available(), reason="quantum extra not installed")
LEDGER_DIR = pathlib.Path(__file__).resolve().parents[1] / "quantum_ledger"


# ---------------------------------------------------------------- portability
def test_ledger_package_has_no_host_imports() -> None:
    """The package must stay copy-pasteable into another project."""
    for path in LEDGER_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert not node.module.startswith("app"), f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("app") for a in node.names), path.name


# ---------------------------------------------------------------- analysis
def test_distribution_metrics() -> None:
    p = {"00": 0.5, "11": 0.5}
    assert total_variation_distance(p, p) == pytest.approx(0)
    assert hellinger_fidelity(p, p) == pytest.approx(1)
    assert total_variation_distance(p, {"01": 1.0}) == pytest.approx(1)
    assert hellinger_fidelity(p, {"01": 1.0}) == pytest.approx(0)
    assert total_variation_distance(p, {"00": 1.0}) == pytest.approx(0.5)


def test_ledger_ising_costs_match_the_territory_energies() -> None:
    rng = np.random.default_rng(3)
    points = [
        Point(str(i), 50.45 + rng.normal(0, 0.02), 30.5 + rng.normal(0, 0.03), 1.0)
        for i in range(7)
    ]
    problem = build_bisection_ising(aggregate(points, 12), 0.5)
    costs = ising_costs(ising_problem_from_arrays(problem.J, problem.h, problem.const))
    assert np.allclose(costs, ising_energies(problem))


def test_compare_scores_against_problem_and_random_baseline() -> None:
    # 2 qubits, cost = z0*z1: optimum = anti-aligned "01"/"10"
    problem = {"kind": "ising", "num_qubits": 2, "h": [0, 0], "J": [[0, 1, 1.0]], "const": 0}
    counts = {"01": 60, "10": 20, "00": 20}
    ideal = {"01": 0.5, "10": 0.5}
    out = compare(counts, ideal, problem)
    assert out["optimal_bitstrings"] == ["01", "10"]
    assert out["measured_optimum_frequency"] == pytest.approx(0.8)
    assert out["uniform_optimum_probability"] == pytest.approx(0.5)
    assert out["lift_over_random"] == pytest.approx(1.6)
    assert out["ideal_optimum_probability"] == pytest.approx(1.0)
    assert out["tvd_vs_ideal"] == pytest.approx(0.5 * (0.1 + 0.3 + 0.2))
    assert out["found_optimum"] is True


# ---------------------------------------------------------------- end-to-end
@needs_qiskit
def test_emulator_job_is_fully_recorded(client: TestClient, scenario: dict) -> None:  # noqa: F811
    plan = _plan(client, scenario, "ibm_emulator", qaoa_reps=1, shots=256).json()
    assert plan["status"] == "completed"
    run = client.get("/api/v1/quantum/runs").json()[0]
    run_detail = client.get(f"/api/v1/quantum/runs/{run['id']}").json()

    records = client.get("/api/v1/quantum/ledger/").json()
    assert len(records) == 1
    summary_row = records[0]
    assert summary_row["id"] == run_detail["details"]["ledger_id"]
    assert summary_row["source_id"] == plan["id"]
    assert summary_row["status"] == "completed"
    assert summary_row["job_id"] == run["job_id"]
    assert summary_row["is_real_hardware"] is False

    rec = client.get(f"/api/v1/quantum/ledger/{summary_row['id']}").json()
    n = rec["num_qubits"]
    # sent
    assert rec["logical_qasm"].startswith("OPENQASM 2.0;")
    assert rec["isa_qasm"] and rec["isa_depth"] >= rec["logical_depth"]
    assert len(rec["physical_qubits"]) == n
    assert rec["parameters"]["reps"] == 1 and len(rec["parameters"]["gammas"]) == 1
    assert rec["problem"]["kind"] == "ising"
    assert rec["calibration"]["qubits"] and rec["calibration"]["qubits"][0]["t1_us"] > 0
    assert rec["calibration"]["couplers"]
    # received
    assert sum(rec["counts"].values()) == 256
    assert len(rec["memory"]) == 256 and all(len(b) == n for b in rec["memory"])
    # CPU reference
    assert sum(rec["cpu_ideal_distribution"].values()) == pytest.approx(1.0)
    assert rec["cpu_ideal_ms"] >= 0
    assert set(rec["classical_reference"]["optimal_bitstrings"]) == set(
        rec["comparison"]["optimal_bitstrings"]
    )
    assert 0 < rec["tvd_vs_ideal"] < 1
    assert 0 < rec["hellinger_fidelity"] <= 1

    analysis = client.get(f"/api/v1/quantum/ledger/{rec['id']}/analysis").json()
    assert analysis["outcomes"] and {"measured_probability", "ideal_probability", "cost"} <= set(
        analysis["outcomes"][0]
    )
    assert len(analysis["qubit_marginals"]) == n
    assert analysis["shot_drift"]
    assert analysis["circuit"]["growth_factor"] >= 1

    summary = client.get("/api/v1/quantum/ledger/summary").json()
    assert summary["total_jobs"] == 1
    assert summary["by_backend"]["fake_brisbane"]["jobs"] == 1


@needs_qiskit
def test_timeout_keeps_the_job_id_for_later_recovery(
    client: TestClient,
    scenario: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow(self, submission, timeout_seconds):
        raise QuantumTimeoutError("still queued")

    monkeypatch.setattr(IbmRuntimeProvider, "wait", slow)
    plan = _plan(client, scenario, "ibm_emulator", qaoa_reps=1, shots=128).json()
    assert plan["status"] == "completed"  # classical fallback

    rec = client.get("/api/v1/quantum/ledger/").json()[0]
    assert rec["status"] == "timeout"
    assert rec["job_id"]
    assert rec["submitted_at"] is not None
    # an emulator job lived only in that request's memory — sync says so honestly
    synced = client.post(f"/api/v1/quantum/ledger/{rec['id']}/sync").json()
    assert synced["status"] == "failed"
    assert "can't be recovered" in synced["error"]


class _FakeService:
    def __init__(self, jobs):
        self.jobs = jobs

    def job(self, job_id):
        return self.jobs[job_id]


class _ErroredJob:
    def status(self):
        return "ERROR"

    def error_message(self):
        return "Error code 1517: instruction not supported"


@needs_qiskit
async def test_sync_recovers_a_real_hardware_result(db_session, test_organization) -> None:
    """Simulates "process died after submit": a real-QPU row left in
    'submitted', then recovered by sync from (here: a stand-in) IBM service."""
    from qiskit import QuantumCircuit
    from qiskit.transpiler import generate_preset_pass_manager
    from qiskit_ibm_runtime import SamplerV2
    from qiskit_ibm_runtime.fake_provider import FakeBrisbane

    backend = FakeBrisbane()
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    isa = generate_preset_pass_manager(optimization_level=1, backend=backend).run(qc)

    ledger = QuantumLedger(db_session, tenant_id=test_organization.id)
    record = await ledger.open(
        source="test",
        provider="ibm_quantum",
        is_real_hardware=True,
        backend=backend,
        logical_circuit=qc,
        isa_circuit=isa,
        shots=200,
    )
    assert record.status == "prepared"
    assert record.cpu_ideal_distribution == pytest.approx({"00": 0.5, "11": 0.5})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        job = SamplerV2(mode=backend).run([isa], shots=200)
    await ledger.mark_submitted(record.id, job.job_id())
    await ledger.mark_timeout(record.id, "request ended before the result")

    service = _FakeService({job.job_id(): job, "bad": _ErroredJob()})
    synced = await ledger.sync_pending(lambda: service)
    assert [r.status for r in synced] == ["completed"]
    done = await ledger.get(record.id)
    assert sum(done.counts.values()) == 200
    assert len(done.memory) == 200
    assert done.sync_attempts == 1
    # Bell state: mostly 00/11 — fidelity vs ideal high, but noise leaves 01/10
    assert done.hellinger_fidelity > 0.8
    assert done.comparison["ideal_support"] == 2

    # an IBM-side failure is stored with IBM's message
    failing = await ledger.open(
        source="test",
        provider="ibm_quantum",
        is_real_hardware=True,
        backend=backend,
        logical_circuit=qc,
        isa_circuit=isa,
        shots=10,
    )
    await ledger.mark_submitted(failing.id, "bad")
    failed = await ledger.sync(failing.id, lambda: service)
    assert failed.status == "failed"
    assert "1517" in failed.error


@needs_qiskit
async def test_ledger_is_tenant_scoped(client: TestClient, db_session, other_organization) -> None:
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(1)
    qc.h(0)
    qc.measure_all()
    from qiskit_ibm_runtime.fake_provider import FakeBrisbane

    record = await QuantumLedger(db_session, tenant_id=other_organization.id).open(
        source="test",
        provider="ibm_emulator",
        is_real_hardware=False,
        backend=FakeBrisbane(),
        logical_circuit=qc,
        isa_circuit=None,
        shots=10,
    )
    assert client.get("/api/v1/quantum/ledger/").json() == []
    assert client.get(f"/api/v1/quantum/ledger/{record.id}").status_code == 404
    assert client.get("/api/v1/quantum/ledger/summary").json()["total_jobs"] == 0


def test_sync_pending_without_ibm_configuration_is_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/quantum/ledger/sync-pending").status_code == 422


def test_ledger_requires_auth(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/api/v1/quantum/ledger/").status_code == 401


@needs_qiskit
def test_back_to_back_emulator_requests_do_not_crash(client: TestClient, scenario: dict) -> None:  # noqa: F811
    """Regression: each TestClient request runs on a fresh event-loop thread;
    before Qiskit work was pinned to one thread (quantum_ledger.runtime) the
    second request segfaulted the process inside QuantumCircuit()."""
    for _ in range(3):
        assert (
            _plan(client, scenario, "ibm_emulator", qaoa_reps=1, shots=128).json()["status"]
            == "completed"
        )
    records = client.get("/api/v1/quantum/ledger/").json()
    assert [r["status"] for r in records] == ["completed"] * 3


@needs_qiskit
def test_emulator_placeholder_metrics_are_not_reported_as_device_timings(
    client: TestClient,
    scenario: dict,  # noqa: F811
) -> None:
    _plan(client, scenario, "ibm_emulator", qaoa_reps=1, shots=128)
    rec = client.get("/api/v1/quantum/ledger/").json()[0]
    assert rec["queue_ms"] is None and rec["qpu_seconds"] is None
    assert rec["execution_ms"] == pytest.approx(rec["wait_wall_ms"]) and rec["execution_ms"] > 0
    run = client.get("/api/v1/quantum/runs").json()[0]
    assert run["queue_ms"] is None and run["execution_ms"] > 0
