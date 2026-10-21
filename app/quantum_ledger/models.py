"""The ledger table: one row per job sent to an IBM backend (real QPU or a
local fake-device emulator) — what was sent, what came back, and what an
ordinary CPU computes for the same circuit.

Self-contained on purpose: its own DeclarativeBase/metadata and no foreign
keys into the host schema (tenant_id / source_id are plain columns), so the
package can be copied into another project as-is. The host registers
`LedgerBase.metadata` with Alembic next to its own metadata.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LedgerBase(DeclarativeBase):
    """Separate metadata so the ledger has no dependency on the host's models."""


def _now() -> datetime:
    return datetime.now(UTC)


class QuantumJobRecord(LedgerBase):
    __tablename__ = "quantum_job_ledger"
    __table_args__ = (
        Index("ix_quantum_job_ledger_tenant_created", "tenant_id", "created_at"),
        Index("ix_quantum_job_ledger_status", "status"),
        Index("ix_quantum_job_ledger_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Who asked: e.g. source="territory_plan", source_id=<plan id>, source_step="AB"
    source: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_step: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # prepared -> submitted -> completed | failed | timeout (still running at
    # IBM, recoverable via sync) | cancelled
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Where it ran (never the API token)
    provider: Mapped[str] = mapped_column(String(32))  # ibm_quantum | ibm_emulator
    is_real_hardware: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backend_name: Mapped[str] = mapped_column(String(100))
    backend_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    backend_num_qubits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primitive: Mapped[str] = mapped_column(String(32), default="sampler")
    job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ---- what we SENT -------------------------------------------------------
    shots: Mapped[int] = mapped_column(Integer)
    num_qubits: Mapped[int] = mapped_column(Integer)
    logical_qasm: Mapped[str] = mapped_column(Text)  # OpenQASM 2, re-loadable
    logical_depth: Mapped[int] = mapped_column(Integer)
    logical_ops: Mapped[dict] = mapped_column(JSON, default=dict)
    isa_qasm: Mapped[str | None] = mapped_column(Text, nullable=True)  # what the device ran
    isa_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isa_ops: Mapped[dict] = mapped_column(JSON, default=dict)
    isa_two_qubit_gates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    physical_qubits: Mapped[list] = mapped_column(JSON, default=list)  # logical i -> physical
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. QAOA γ/β
    run_options: Mapped[dict] = mapped_column(JSON, default=dict)
    # Optional problem the circuit encodes, so results can be scored later:
    # {"kind": "ising", "num_qubits": n, "h": [...], "J": [[i, j, v], ...], "const": c}
    problem: Mapped[dict] = mapped_column(JSON, default=dict)
    # Device state at submit time for the qubits/couplers actually used:
    # T1/T2, readout and gate errors, calibration timestamp
    calibration: Mapped[dict] = mapped_column(JSON, default=dict)

    # ---- what we GOT BACK ---------------------------------------------------
    counts: Mapped[dict] = mapped_column(JSON, default=dict)  # bitstring -> shots
    memory: Mapped[list] = mapped_column(JSON, default=list)  # per-shot bitstrings, in order
    result_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    job_metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # raw IBM job.metrics()
    ibm_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ---- the same thing on an ordinary CPU ----------------------------------
    # Exact noiseless output distribution of the logical circuit (statevector)
    cpu_ideal_distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    # The caller's classical solver for the underlying problem, if any:
    # {"method": ..., "optimal_cost": ..., "optimal_bitstrings": [...], "solve_ms": ...}
    classical_reference: Mapped[dict] = mapped_column(JSON, default=dict)
    # Optional: the device's own noise model run locally (Aer) — "what the
    # model predicted" vs "what the hardware did"
    cpu_noisy_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    # Derived comparison: TVD, Hellinger fidelity, entropies, costs, optimum
    # hit rates, lift over random — recomputable from the columns above
    comparison: Mapped[dict] = mapped_column(JSON, default=dict)

    # Headline numbers duplicated as columns so they can be filtered/charted in SQL
    tvd_vs_ideal: Mapped[float | None] = mapped_column(Float, nullable=True)
    hellinger_fidelity: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_optimum_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    ideal_optimum_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- timings ------------------------------------------------------------
    transpile_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_ideal_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_noisy_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    classical_solve_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # on the device
    wait_wall_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # our blocking wait
    qpu_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)  # billed usage
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
