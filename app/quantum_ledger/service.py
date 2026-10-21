"""QuantumLedger — durable record of every job sent to an IBM backend.

Write order guarantees a paid job is never lost:

    open()            row "prepared": circuits, calibration, CPU ideal
                      distribution — all BEFORE anything is sent
    mark_submitted()  job_id committed right after submit returns
    complete()        raw counts + per-shot memory + IBM metadata, then the
                      CPU comparison is (re)computed from stored columns
    mark_timeout()    still running at IBM — `sync()` fetches it later
    fail()            error text kept with whatever was known

If the process dies between submit and result, the row stays "submitted"
with its job_id, and `sync_pending()` recovers the result from IBM.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .analysis import (
    calibration_snapshot,
    circuit_summary,
    compare,
    ideal_distribution,
    memory_drift,
    outcome_table,
    per_qubit_marginals,
    qasm2,
)
from .ibm import (
    CANCELLED_STATUSES,
    DONE_STATUSES,
    FAILED_STATUSES,
    ExtractedResult,
    extract,
    status_name,
)
from .models import QuantumJobRecord
from .runtime import run_qiskit

RECOVERABLE_STATUSES = ("submitted", "timeout")


def _now() -> datetime:
    return datetime.now(UTC)


class LedgerNotFoundError(Exception):
    pass


def _describe_circuits(backend, logical_circuit, isa_circuit) -> dict:
    """All Qiskit-touching work of `open`, run on the Qiskit thread."""
    layout = (
        isa_circuit.layout.final_index_layout()
        if isa_circuit is not None and isa_circuit.layout is not None
        else list(range(logical_circuit.num_qubits))
    )
    ideal, ideal_ms = ideal_distribution(logical_circuit)
    return {
        "logical": circuit_summary(logical_circuit),
        "isa": circuit_summary(isa_circuit) if isa_circuit is not None else None,
        "layout": layout,
        "ideal": ideal,
        "ideal_ms": ideal_ms,
        "logical_qasm": qasm2(logical_circuit),
        "isa_qasm": qasm2(isa_circuit) if isa_circuit is not None else None,
        "calibration": calibration_snapshot(backend, layout, isa_circuit),
    }


class QuantumLedger:
    """Async, tenant-scoped access to the ledger. `tenant_id=None` = unscoped
    (single-tenant apps, admin tools)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    # ------------------------------------------------------------ queries
    def _scoped(self, stmt):
        if self.tenant_id is not None:
            stmt = stmt.where(QuantumJobRecord.tenant_id == self.tenant_id)
        return stmt

    async def get(self, record_id: uuid.UUID) -> QuantumJobRecord | None:
        stmt = self._scoped(select(QuantumJobRecord).where(QuantumJobRecord.id == record_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        backend_name: str | None = None,
        source_id: str | None = None,
        real_hardware: bool | None = None,
    ) -> list[QuantumJobRecord]:
        stmt = self._scoped(select(QuantumJobRecord))
        if status:
            stmt = stmt.where(QuantumJobRecord.status == status)
        if backend_name:
            stmt = stmt.where(QuantumJobRecord.backend_name == backend_name)
        if source_id:
            stmt = stmt.where(QuantumJobRecord.source_id == source_id)
        if real_hardware is not None:
            stmt = stmt.where(QuantumJobRecord.is_real_hardware == real_hardware)
        stmt = stmt.order_by(QuantumJobRecord.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _require(self, record_id: uuid.UUID) -> QuantumJobRecord:
        record = await self.get(record_id)
        if record is None:
            raise LedgerNotFoundError(str(record_id))
        return record

    async def _save(self, record: QuantumJobRecord) -> QuantumJobRecord:
        record.updated_at = _now()
        await self.session.commit()
        await self.session.refresh(record)
        return record

    # ------------------------------------------------------------ lifecycle
    async def open(
        self,
        *,
        source: str,
        provider: str,
        is_real_hardware: bool,
        backend,
        logical_circuit,
        isa_circuit,
        shots: int,
        source_id: str | None = None,
        source_step: str | None = None,
        parameters: dict | None = None,
        run_options: dict | None = None,
        problem: dict | None = None,
        classical_reference: dict | None = None,
        transpile_ms: float | None = None,
        channel: str | None = None,
        instance: str | None = None,
    ) -> QuantumJobRecord:
        """Persist everything known before submit. Computing the CPU ideal
        distribution here (not after) means it's available even when the
        result is recovered later by `sync`."""
        described = await run_qiskit(_describe_circuits, backend, logical_circuit, isa_circuit)
        logical, isa, layout = described["logical"], described["isa"], described["layout"]
        ideal, ideal_ms = described["ideal"], described["ideal_ms"]
        reference = dict(classical_reference or {})
        record = QuantumJobRecord(
            tenant_id=self.tenant_id,
            source=source,
            source_id=source_id,
            source_step=source_step,
            status="prepared",
            provider=provider,
            is_real_hardware=is_real_hardware,
            channel=channel,
            instance=instance,
            backend_name=getattr(backend, "name", str(backend)),
            backend_version=str(getattr(backend, "backend_version", "") or "") or None,
            backend_num_qubits=getattr(backend, "num_qubits", None),
            shots=shots,
            num_qubits=logical_circuit.num_qubits,
            logical_qasm=described["logical_qasm"],
            logical_depth=logical["depth"],
            logical_ops=logical["ops"],
            isa_qasm=described["isa_qasm"],
            isa_depth=isa["depth"] if isa else None,
            isa_ops=isa["ops"] if isa else {},
            isa_two_qubit_gates=isa["two_qubit_gates"] if isa else None,
            physical_qubits=[int(q) for q in layout],
            parameters=parameters or {},
            run_options=run_options or {},
            problem=problem or {},
            calibration=described["calibration"],
            cpu_ideal_distribution=ideal,
            cpu_ideal_ms=ideal_ms,
            classical_reference=reference,
            classical_solve_ms=reference.get("solve_ms"),
            transpile_ms=transpile_ms,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def mark_submitted(self, record_id: uuid.UUID, job_id: str | None) -> QuantumJobRecord:
        record = await self._require(record_id)
        record.status = "submitted"
        record.job_id = job_id
        record.submitted_at = _now()
        return await self._save(record)

    async def complete(
        self,
        record_id: uuid.UUID,
        extracted: ExtractedResult,
        *,
        wait_wall_ms: float | None = None,
        noisy_counts: dict[str, int] | None = None,
        noisy_ms: float | None = None,
    ) -> QuantumJobRecord:
        record = await self._require(record_id)
        record.status = "completed"
        record.error = None
        record.counts = extracted.counts
        record.memory = extracted.memory
        record.result_metadata = extracted.result_metadata
        record.job_metrics = extracted.job_metrics
        record.ibm_status = extracted.ibm_status
        if record.is_real_hardware:
            record.qpu_seconds = extracted.qpu_seconds
            record.queue_ms = extracted.queue_ms
            record.execution_ms = extracted.execution_ms
            record.started_at = extracted.started_at
            record.finished_at = extracted.finished_at
        # else: local fake-backend jobs return placeholder metrics (identical
        # timestamps, zero usage) — kept raw in job_metrics, not trusted here
        record.session_id = extracted.session_id or record.session_id
        record.received_at = _now()
        if wait_wall_ms is not None:
            record.wait_wall_ms = wait_wall_ms
            if record.execution_ms is None and not record.is_real_hardware:
                record.execution_ms = wait_wall_ms  # local emulator: wall time is all there is
        if noisy_counts is not None:
            record.cpu_noisy_counts = noisy_counts
            record.cpu_noisy_ms = noisy_ms
        self._apply_comparison(record)
        return await self._save(record)

    async def mark_timeout(self, record_id: uuid.UUID, error: str) -> QuantumJobRecord:
        record = await self._require(record_id)
        record.status = "timeout"
        record.error = error
        return await self._save(record)

    async def fail(
        self, record_id: uuid.UUID, error: str, ibm_status: str | None = None
    ) -> QuantumJobRecord:
        record = await self._require(record_id)
        record.status = "failed"
        record.error = error
        record.ibm_status = ibm_status or record.ibm_status
        return await self._save(record)

    @staticmethod
    def _apply_comparison(record: QuantumJobRecord) -> None:
        comparison = compare(
            record.counts or {},
            record.cpu_ideal_distribution or {},
            record.problem or {},
            record.cpu_noisy_counts or None,
        )
        record.comparison = comparison
        record.tvd_vs_ideal = comparison.get("tvd_vs_ideal")
        record.hellinger_fidelity = comparison.get("hellinger_fidelity")
        record.measured_optimum_frequency = comparison.get("measured_optimum_frequency")
        record.ideal_optimum_probability = comparison.get("ideal_optimum_probability")

    async def recompute(self, record_id: uuid.UUID) -> QuantumJobRecord:
        """Re-derive the comparison from stored columns (e.g. after adding metrics)."""
        record = await self._require(record_id)
        if record.counts:
            self._apply_comparison(record)
        return await self._save(record)

    # ------------------------------------------------------------ recovery
    async def sync(
        self, record_id: uuid.UUID, runtime_service_factory: Callable | None
    ) -> QuantumJobRecord:
        """Ask IBM about a submitted/timed-out job and store its result if done.

        Only real-hardware jobs are recoverable: local emulator jobs live in
        process memory and are gone once the request that ran them ends.
        """
        record = await self._require(record_id)
        if record.status not in RECOVERABLE_STATUSES or not record.job_id:
            return record
        if not record.is_real_hardware:
            return await self.fail(
                record_id, "Local emulator job can't be recovered after the process that ran it"
            )
        if runtime_service_factory is None:
            raise RuntimeError("No IBM runtime service configured")

        record.sync_attempts = (record.sync_attempts or 0) + 1
        record.last_synced_at = _now()
        await self._save(record)

        service = await run_qiskit(runtime_service_factory)
        job = await run_qiskit(service.job, record.job_id)
        status = await run_qiskit(status_name, job)
        if status in DONE_STATUSES:
            extracted = await run_qiskit(lambda: extract(job, job.result()))
            return await self.complete(record_id, extracted)
        if status in FAILED_STATUSES:
            message = None
            try:
                message = job.error_message()
            except Exception:
                pass
            return await self.fail(
                record_id, message or f"IBM job ended with {status}", ibm_status=status
            )
        if status in CANCELLED_STATUSES:
            record = await self._require(record_id)
            record.status = "cancelled"
            record.ibm_status = status
            return await self._save(record)
        record = await self._require(record_id)
        record.ibm_status = status  # QUEUED / RUNNING — try again later
        return await self._save(record)

    async def sync_pending(
        self, runtime_service_factory: Callable | None, limit: int = 50
    ) -> list[QuantumJobRecord]:
        stmt = self._scoped(
            select(QuantumJobRecord)
            .where(
                QuantumJobRecord.status.in_(RECOVERABLE_STATUSES),
                QuantumJobRecord.job_id.is_not(None),
                QuantumJobRecord.is_real_hardware.is_(True),
            )
            .order_by(QuantumJobRecord.created_at)
            .limit(limit)
        )
        pending = list((await self.session.execute(stmt)).scalars().all())
        synced = []
        for record in pending:
            try:
                synced.append(await self.sync(record.id, runtime_service_factory))
            except Exception as exc:  # one bad job must not block the rest
                record = await self._require(record.id)
                record.error = f"sync failed: {type(exc).__name__}: {exc}"
                synced.append(await self._save(record))
        return synced

    # ------------------------------------------------------------ analysis views
    @staticmethod
    def analysis(record: QuantumJobRecord) -> dict:
        """Chart-ready breakdown of one record for the frontend."""
        timeline = [
            ("created", record.created_at),
            ("submitted", record.submitted_at),
            ("started_on_device", record.started_at),
            ("finished_on_device", record.finished_at),
            ("received", record.received_at),
        ]
        return {
            "id": str(record.id),
            "status": record.status,
            "backend_name": record.backend_name,
            "is_real_hardware": record.is_real_hardware,
            "comparison": record.comparison or {},
            "outcomes": outcome_table(
                record.counts or {}, record.cpu_ideal_distribution or {}, record.problem
            ),
            "qubit_marginals": per_qubit_marginals(
                record.counts or {}, record.cpu_ideal_distribution or {}, record.num_qubits
            ),
            "shot_drift": memory_drift(record.memory or [], record.problem),
            "timeline": [{"event": e, "at": t.isoformat() if t else None} for e, t in timeline],
            "timings_ms": {
                "transpile": record.transpile_ms,
                "cpu_ideal_statevector": record.cpu_ideal_ms,
                "cpu_noise_model": record.cpu_noisy_ms,
                "classical_solver": record.classical_solve_ms,
                "queue": record.queue_ms,
                "execution_on_device": record.execution_ms,
                "our_wait": record.wait_wall_ms,
            },
            "qpu_seconds": record.qpu_seconds,
            "circuit": {
                "logical": {"depth": record.logical_depth, "ops": record.logical_ops},
                "isa": {
                    "depth": record.isa_depth,
                    "ops": record.isa_ops,
                    "two_qubit_gates": record.isa_two_qubit_gates,
                },
                "physical_qubits": record.physical_qubits,
                "growth_factor": (record.isa_depth / record.logical_depth)
                if record.isa_depth and record.logical_depth
                else None,
            },
            "calibration": record.calibration or {},
            "classical_reference": record.classical_reference or {},
        }

    async def summary(self) -> dict:
        records = await self.list(limit=10_000)
        done = [r for r in records if r.status == "completed"]

        def stats(values):
            values = [v for v in values if v is not None]
            if not values:
                return {"count": 0}
            arr = np.array(values, dtype=float)
            return {
                "count": len(values),
                "avg": float(arr.mean()),
                "p50": float(np.percentile(arr, 50)),
                "p95": float(np.percentile(arr, 95)),
                "max": float(arr.max()),
            }

        def avg(values):
            values = [v for v in values if v is not None]
            return mean(values) if values else None

        by_backend: dict[str, dict] = {}
        for name in sorted({r.backend_name for r in done}):
            rows = [r for r in done if r.backend_name == name]
            by_backend[name] = {
                "jobs": len(rows),
                "real_hardware": rows[0].is_real_hardware,
                "avg_tvd_vs_ideal": avg([r.tvd_vs_ideal for r in rows]),
                "avg_hellinger_fidelity": avg([r.hellinger_fidelity for r in rows]),
                "avg_lift_over_random": avg(
                    [(r.comparison or {}).get("lift_over_random") for r in rows]
                ),
            }
        return {
            "total_jobs": len(records),
            "by_status": {
                s: sum(r.status == s for r in records) for s in sorted({r.status for r in records})
            },
            "real_hardware_jobs": sum(r.is_real_hardware for r in records),
            "pending_recovery": sum(
                r.status in RECOVERABLE_STATUSES and r.is_real_hardware for r in records
            ),
            "total_shots": sum(r.shots for r in done),
            "total_qpu_seconds": float(sum(r.qpu_seconds or 0 for r in done)),
            "by_backend": by_backend,
            "tvd_vs_ideal": stats([r.tvd_vs_ideal for r in done]),
            "hellinger_fidelity": stats([r.hellinger_fidelity for r in done]),
            "queue_ms": stats([r.queue_ms for r in done]),
            "execution_ms": stats([r.execution_ms for r in done]),
            "cpu_ideal_ms": stats([r.cpu_ideal_ms for r in done]),
            "classical_solve_ms": stats([r.classical_solve_ms for r in done]),
            "transpile_ms": stats([r.transpile_ms for r in done]),
            "isa_depth": stats([r.isa_depth for r in done]),
            "last_job_at": max((r.created_at for r in records), default=None),
        }
