"""Quantum lab API routes: what was sent to which quantum backend, when, how
long each phase took and how good the answer was.

Visible to every authenticated user of the organization for now; gate it
behind an admin role once roles exist.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.core.dependencies import get_current_user, get_quantum_run_repository
from app.repositories.quantum_run_repository import QuantumRunRepository
from app.schemas.quantum import QuantumRunDetail, QuantumRunRead, QuantumSummary
from app.services.territory.metrics import summarize_runs
from app.services.territory.service import available_solvers

router = APIRouter(tags=["quantum"], dependencies=[Depends(get_current_user)])


@router.get("/runs", response_model=list[QuantumRunRead])
async def list_quantum_runs(
    limit: int = Query(default=100, ge=1, le=500),
    territory_plan_id: uuid.UUID | None = None,
    repo: QuantumRunRepository = Depends(get_quantum_run_repository),
) -> list[QuantumRunRead]:
    """Newest quantum runs first, optionally only those of one territory plan."""
    runs = await repo.list_recent(limit=limit, territory_plan_id=territory_plan_id)
    return [QuantumRunRead.model_validate(r) for r in runs]


@router.get("/runs/{run_id}", response_model=QuantumRunDetail)
async def get_quantum_run(
    run_id: uuid.UUID,
    repo: QuantumRunRepository = Depends(get_quantum_run_repository),
) -> QuantumRunDetail:
    """One run with full details: QAOA angles, top measured bitstrings, IBM
    job timestamps/usage, transpiled gate counts."""
    run = await repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Quantum run not found")
    return QuantumRunDetail.model_validate(run)


@router.get("/summary", response_model=QuantumSummary)
async def get_quantum_summary(
    repo: QuantumRunRepository = Depends(get_quantum_run_repository),
) -> QuantumSummary:
    """Aggregates over all runs: status mix, timing percentiles per phase,
    quality vs. random guessing, QPU budget use, which solvers are available."""
    settings = get_settings()
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return summarize_runs(
        await repo.list_recent(limit=10_000),
        qpu_seconds_this_month=await repo.qpu_seconds_since(month_start, "ibm_quantum"),
        qpu_monthly_budget_seconds=settings.IBM_QUANTUM_MONTHLY_BUDGET_SECONDS,
        solvers=available_solvers(settings),
    )
