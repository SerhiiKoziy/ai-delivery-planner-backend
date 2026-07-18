"""Driver persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.driver import Driver
from app.repositories.base import TenantScopedRepository


class DriverRepository(TenantScopedRepository[Driver]):
    """Repository for Driver records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, Driver, organization_id)
