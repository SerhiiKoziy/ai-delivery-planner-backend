"""QuantumRun model — one interaction with a quantum backend (simulator,
local IBM emulator or a real IBM QPU) during a territory-plan recalculation.

One row per bisection step that went to a quantum backend. Written as soon
as a job is submitted (status "submitted", with its job_id) and updated when
the result arrives, so a paid QPU job is never lost to a crash mid-wait.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class QuantumRun(Base):
    __tablename__ = "quantum_runs"
    __table_args__ = (
        Index("ix_quantum_runs_organization_id_created_at", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))
    territory_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("territory_plans.id"), index=True
    )
    # Position in the recursive bisection: "root", "A", "B", "AB", ...
    step: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    backend_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # submitted | completed | failed | timeout | budget_exceeded
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Problem / circuit shape
    num_qubits: Mapped[int] = mapped_column(Integer)
    num_terms: Mapped[int] = mapped_column(Integer, default=0)
    qaoa_reps: Mapped[int] = mapped_column(Integer)
    shots: Mapped[int] = mapped_column(Integer)
    logical_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    two_qubit_gates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transpiled_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transpiled_two_qubit_gates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    optimizer_evaluations: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timings, milliseconds (qpu_seconds is IBM's billed quantum time)
    build_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    classical_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    optimize_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    transpile_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    qpu_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Result quality (energies are of the normalized Ising cost; lower = better)
    expected_energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    optimal_energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    approximation_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    optimum_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampled_optimum_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    unique_bitstrings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which answer the plan used for this step: "quantum" (sample matched
    # the optimum) or "classical" (fallback / quantum sample was worse)
    chosen_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # QAOA angles, top counts, raw IBM timestamps/usage, uniform baseline, ...
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    @property
    def uniform_optimum_probability(self) -> float | None:
        """Chance a uniformly random bitstring is optimal — the "no quantum" baseline."""
        return (self.details or {}).get("uniform_optimum_probability")
