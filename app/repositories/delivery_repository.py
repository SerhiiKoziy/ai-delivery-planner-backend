"""Delivery persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.delivery import Delivery
from app.repositories.base import BaseRepository


class DeliveryRepository(BaseRepository[Delivery]):
    """Repository for Delivery records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Delivery)
