"""Quantum-run log schemas (the "Quantum lab" dashboard tab)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QuantumRunRead(BaseModel):
    id: uuid.UUID
    territory_plan_id: uuid.UUID
    step: str
    provider: str
    backend_name: str | None = None
    status: str
    error: str | None = None
    job_id: str | None = None

    num_qubits: int
    num_terms: int
    qaoa_reps: int
    shots: int
    logical_depth: int | None = None
    two_qubit_gates: int | None = None
    transpiled_depth: int | None = None
    transpiled_two_qubit_gates: int | None = None
    optimizer_evaluations: int | None = None

    build_ms: float | None = None
    classical_ms: float | None = None
    optimize_ms: float | None = None
    transpile_ms: float | None = None
    queue_ms: float | None = None
    execution_ms: float | None = None
    total_ms: float | None = None
    qpu_seconds: float | None = None

    expected_energy: float | None = None
    best_energy: float | None = None
    optimal_energy: float | None = None
    approximation_ratio: float | None = None
    optimum_probability: float | None = None
    sampled_optimum_frequency: float | None = None
    unique_bitstrings: int | None = None
    chosen_source: str | None = None
    uniform_optimum_probability: float | None = None

    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuantumRunDetail(QuantumRunRead):
    details: dict


class TimingStats(BaseModel):
    count: int
    avg_ms: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None


class SolverAvailability(BaseModel):
    available: bool
    reason: str | None = None


class QuantumSummary(BaseModel):
    total_runs: int
    runs_by_status: dict[str, int]
    runs_by_provider: dict[str, int]
    quantum_matched_optimum_rate: float | None = None
    avg_approximation_ratio: float | None = None
    avg_optimum_probability: float | None = None
    avg_uniform_optimum_probability: float | None = None
    avg_sampled_optimum_frequency: float | None = None
    # sampled optimum frequency / uniform optimum probability: 1.0 = no
    # better than random bitstrings; the honest "did quantum help" number
    avg_lift_over_random: float | None = None
    # chance that `shots` uniformly random bitstrings contain an optimum at
    # least once — "quantum matched the optimum" means little when this is high
    avg_random_hit_probability: float | None = None
    total_shots: int
    timings: dict[str, TimingStats]
    qpu_seconds_this_month: float
    qpu_monthly_budget_seconds: float
    last_run_at: datetime | None = None
    solvers: dict[str, SolverAvailability]
