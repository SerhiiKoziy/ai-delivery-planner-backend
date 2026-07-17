"""Driver persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.driver import Driver
from app.repositories.base import BaseRepository


class DriverRepository(BaseRepository[Driver]):
    """Repository for Driver records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Driver)
