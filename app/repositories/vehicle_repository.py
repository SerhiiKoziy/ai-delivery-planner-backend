"""Vehicle persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vehicle import Vehicle
from app.repositories.base import BaseRepository


class VehicleRepository(BaseRepository[Vehicle]):
    """Repository for Vehicle records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Vehicle)
