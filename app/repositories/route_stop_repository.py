"""RouteStop persistence access."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.route_stop import RouteStop
from app.repositories.base import BaseRepository


class RouteStopRepository(BaseRepository[RouteStop]):
    """Repository for RouteStop records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RouteStop)

    async def list_by_route(self, route_id) -> list[RouteStop]:
        """Fetch all stops for a route, ordered by sequence."""
        stmt = (
            select(RouteStop)
            .where(RouteStop.route_id == route_id)
            .order_by(RouteStop.sequence)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_ids(self, ids: list[uuid.UUID]) -> None:
        """Delete multiple stops by id. Loop-delete, matching this codebase's
        simplicity level — no bulk SQL statement."""
        for stop_id in ids:
            await self.delete(stop_id)
