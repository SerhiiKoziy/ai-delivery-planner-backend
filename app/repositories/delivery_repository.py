"""Delivery persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.delivery import Delivery
from app.repositories.base import TenantScopedRepository


class DeliveryRepository(TenantScopedRepository[Delivery]):
    """Repository for Delivery records, scoped to one organization."""

    def __init__(self, session: AsyncSession, organization_id) -> None:
        super().__init__(session, Delivery, organization_id)
