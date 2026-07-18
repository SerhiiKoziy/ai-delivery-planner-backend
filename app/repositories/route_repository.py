"""Route persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.route import Route
from app.repositories.base import TenantScopedRepository


class RouteRepository(TenantScopedRepository[Route]):
    """Repository for Route records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, Route, organization_id)
