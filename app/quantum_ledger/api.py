"""FastAPI router factory for the ledger.

The host passes two dependencies, so this file needs nothing from the host:

    router = build_ledger_router(
        get_ledger=...,            # Depends-able -> QuantumLedger (session + tenant)
        get_runtime_service=...,   # Depends-able -> zero-arg factory returning a
                                   # QiskitRuntimeService, or None if not configured
    )
    app.include_router(router, prefix="/api/v1/quantum/ledger", dependencies=[auth])
"""

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from .schemas import LedgerRecordDetail, LedgerRecordSummary
from .service import QuantumLedger


def build_ledger_router(get_ledger: Callable, get_runtime_service: Callable) -> APIRouter:
    router = APIRouter(tags=["quantum-ledger"])

    async def _record_or_404(ledger: QuantumLedger, record_id: uuid.UUID):
        record = await ledger.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Ledger record not found")
        return record

    @router.get("/", response_model=list[LedgerRecordSummary])
    async def list_records(
        limit: int = Query(default=100, ge=1, le=1000),
        status: str | None = None,
        backend_name: str | None = None,
        source_id: str | None = None,
        real_hardware: bool | None = None,
        ledger: QuantumLedger = Depends(get_ledger),
    ):
        """Jobs sent to IBM backends, newest first."""
        records = await ledger.list(
            limit=limit,
            status=status,
            backend_name=backend_name,
            source_id=source_id,
            real_hardware=real_hardware,
        )
        return [LedgerRecordSummary.model_validate(r) for r in records]

    @router.get("/summary")
    async def summary(ledger: QuantumLedger = Depends(get_ledger)) -> dict:
        """Aggregates: status mix, per-backend fidelity, timing percentiles, QPU use."""
        return await ledger.summary()

    @router.post("/sync-pending", response_model=list[LedgerRecordSummary])
    async def sync_pending(
        ledger: QuantumLedger = Depends(get_ledger),
        runtime_service=Depends(get_runtime_service),
    ):
        """Fetch results of every submitted/timed-out real-QPU job from IBM."""
        if runtime_service is None:
            raise HTTPException(status_code=422, detail="IBM runtime service is not configured")
        return [
            LedgerRecordSummary.model_validate(r)
            for r in await ledger.sync_pending(runtime_service)
        ]

    @router.get("/{record_id}", response_model=LedgerRecordDetail)
    async def get_record(record_id: uuid.UUID, ledger: QuantumLedger = Depends(get_ledger)):
        """Full record: circuits (QASM), calibration, raw counts, per-shot memory,
        IBM metadata, CPU ideal distribution, classical reference."""
        return LedgerRecordDetail.model_validate(await _record_or_404(ledger, record_id))

    @router.get("/{record_id}/analysis")
    async def get_analysis(
        record_id: uuid.UUID, ledger: QuantumLedger = Depends(get_ledger)
    ) -> dict:
        """Chart-ready comparison of device output vs. CPU references."""
        return ledger.analysis(await _record_or_404(ledger, record_id))

    @router.post("/{record_id}/sync", response_model=LedgerRecordSummary)
    async def sync_record(
        record_id: uuid.UUID,
        ledger: QuantumLedger = Depends(get_ledger),
        runtime_service=Depends(get_runtime_service),
    ):
        """Ask IBM for this job's current state/result (recovery after timeout/crash)."""
        record = await _record_or_404(ledger, record_id)
        if record.is_real_hardware and runtime_service is None:
            raise HTTPException(status_code=422, detail="IBM runtime service is not configured")
        return LedgerRecordSummary.model_validate(await ledger.sync(record_id, runtime_service))

    @router.post("/{record_id}/recompute", response_model=LedgerRecordSummary)
    async def recompute(record_id: uuid.UUID, ledger: QuantumLedger = Depends(get_ledger)):
        """Re-derive comparison metrics from stored raw data."""
        await _record_or_404(ledger, record_id)
        return LedgerRecordSummary.model_validate(await ledger.recompute(record_id))

    return router
