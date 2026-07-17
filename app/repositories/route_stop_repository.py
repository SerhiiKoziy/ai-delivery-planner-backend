"""RouteStop persistence access."""

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
