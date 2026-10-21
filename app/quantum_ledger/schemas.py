"""Response models for the ledger API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LedgerRecordSummary(BaseModel):
    """One row of the list view — no circuits, counts or per-shot memory."""

    id: uuid.UUID
    source: str
    source_id: str | None = None
    source_step: str | None = None
    status: str
    error: str | None = None
    provider: str
    is_real_hardware: bool
    backend_name: str
    job_id: str | None = None
    shots: int
    num_qubits: int
    logical_depth: int
    isa_depth: int | None = None
    isa_two_qubit_gates: int | None = None
    tvd_vs_ideal: float | None = None
    hellinger_fidelity: float | None = None
    measured_optimum_frequency: float | None = None
    ideal_optimum_probability: float | None = None
    transpile_ms: float | None = None
    cpu_ideal_ms: float | None = None
    classical_solve_ms: float | None = None
    queue_ms: float | None = None
    execution_ms: float | None = None
    wait_wall_ms: float | None = None
    qpu_seconds: float | None = None
    ibm_status: str | None = None
    sync_attempts: int = 0
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    received_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LedgerRecordDetail(LedgerRecordSummary):
    """Everything stored: what was sent, what came back, CPU references."""

    channel: str | None = None
    instance: str | None = None
    backend_version: str | None = None
    backend_num_qubits: int | None = None
    primitive: str
    session_id: str | None = None
    logical_qasm: str
    logical_ops: dict
    isa_qasm: str | None = None
    isa_ops: dict
    physical_qubits: list
    parameters: dict
    run_options: dict
    problem: dict
    calibration: dict
    counts: dict
    memory: list
    result_metadata: dict
    job_metrics: dict
    cpu_ideal_distribution: dict
    classical_reference: dict
    cpu_noisy_counts: dict
    cpu_noisy_ms: float | None = None
    comparison: dict
    last_synced_at: datetime | None = None
    updated_at: datetime
