"""Route persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.route import Route
from app.repositories.base import BaseRepository


class RouteRepository(BaseRepository[Route]):
    """Repository for Route records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Route)
