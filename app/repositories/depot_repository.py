"""Depot persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.depot import Depot
from app.repositories.base import BaseRepository


class DepotRepository(BaseRepository[Depot]):
    """Repository for Depot records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Depot)
