"""TerritoryPlan persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.territory_plan import TerritoryPlan
from app.repositories.base import TenantScopedRepository


class TerritoryPlanRepository(TenantScopedRepository[TerritoryPlan]):
    """Repository for TerritoryPlan records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, TerritoryPlan, organization_id)
