"""Vehicle persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vehicle import Vehicle
from app.repositories.base import TenantScopedRepository


class VehicleRepository(TenantScopedRepository[Vehicle]):
    """Repository for Vehicle records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, Vehicle, organization_id)
