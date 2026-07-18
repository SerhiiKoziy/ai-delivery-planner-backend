"""Depot persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.depot import Depot
from app.repositories.base import TenantScopedRepository


class DepotRepository(TenantScopedRepository[Depot]):
    """Repository for Depot records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, Depot, organization_id)
