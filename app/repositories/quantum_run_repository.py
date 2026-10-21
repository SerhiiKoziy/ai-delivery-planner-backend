"""QuantumRun persistence access."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.quantum_run import QuantumRun
from app.repositories.base import TenantScopedRepository


class QuantumRunRepository(TenantScopedRepository[QuantumRun]):
    """Repository for QuantumRun records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, QuantumRun, organization_id)

    async def list_recent(
        self, limit: int = 100, territory_plan_id: uuid.UUID | None = None
    ) -> list[QuantumRun]:
        """Newest runs first, optionally only those of one territory plan."""
        stmt = select(QuantumRun).where(QuantumRun.organization_id == self.organization_id)
        if territory_plan_id is not None:
            stmt = stmt.where(QuantumRun.territory_plan_id == territory_plan_id)
        stmt = stmt.order_by(QuantumRun.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_plan(self, territory_plan_id: uuid.UUID) -> list[QuantumRun]:
        """All runs of one plan, in execution order."""
        stmt = (
            select(QuantumRun)
            .where(
                QuantumRun.organization_id == self.organization_id,
                QuantumRun.territory_plan_id == territory_plan_id,
            )
            .order_by(QuantumRun.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def qpu_seconds_since(self, since: datetime, provider: str) -> float:
        """Billed QPU seconds this organization used on `provider` since `since`."""
        stmt = select(func.coalesce(func.sum(QuantumRun.qpu_seconds), 0.0)).where(
            QuantumRun.organization_id == self.organization_id,
            QuantumRun.provider == provider,
            QuantumRun.created_at >= since,
        )
        result = await self.session.execute(stmt)
        return float(result.scalar_one())
