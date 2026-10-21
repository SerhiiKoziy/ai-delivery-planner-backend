"""Territory plan API routes.

POST /plans recalculates zones; when the solver is quantum, every bisection
step is logged as a QuantumRun (see /api/v1/quantum). Runs synchronously:
the simulator/emulator finish in seconds, and a real-QPU wait is bounded by
IBM_QUANTUM_TIMEOUT_SECONDS with a classical fallback.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (
    get_current_user,
    get_territory_plan_repository,
    get_territory_service,
)
from app.repositories.territory_plan_repository import TerritoryPlanRepository
from app.schemas.territory import TerritoryPlanRead, TerritoryPlanRequest
from app.services.territory.service import SolverUnavailableError, TerritoryService

router = APIRouter(tags=["territories"], dependencies=[Depends(get_current_user)])


@router.post("/plans", response_model=TerritoryPlanRead)
async def create_territory_plan(
    payload: TerritoryPlanRequest,
    service: TerritoryService = Depends(get_territory_service),
) -> TerritoryPlanRead:
    """(Re)calculate zones: one zone per vehicle, balanced by stops or weight."""
    try:
        plan = await service.create_plan(payload)
    except SolverUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TerritoryPlanRead.model_validate(plan)


@router.get("/plans", response_model=list[TerritoryPlanRead])
async def list_territory_plans(
    repo: TerritoryPlanRepository = Depends(get_territory_plan_repository),
) -> list[TerritoryPlanRead]:
    """List territory plans for the current organization, newest first."""
    return [TerritoryPlanRead.model_validate(p) for p in await repo.list()]


@router.get("/plans/{plan_id}", response_model=TerritoryPlanRead)
async def get_territory_plan(
    plan_id: uuid.UUID,
    repo: TerritoryPlanRepository = Depends(get_territory_plan_repository),
) -> TerritoryPlanRead:
    plan = await repo.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Territory plan not found")
    return TerritoryPlanRead.model_validate(plan)
