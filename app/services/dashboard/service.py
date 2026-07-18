"""Dashboard overview: aggregate operational stats across today's activity."""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.delivery import Delivery
from app.db.models.driver import Driver
from app.db.models.route import Route
from app.db.models.route_stop import RouteStop
from app.schemas.dashboard import DashboardOverview


class DashboardService:
    """Computes headline dashboard metrics from current DB state.

    "Today" and "late" are approximations: the schema has no explicit
    delivery-date or actual-arrival column yet (see TODOs on the Delivery/
    RouteStop models), so today's activity is inferred from `created_at`,
    and lateness from `estimated_arrival` (a time-of-day, not a timestamp)
    versus the current time for stops on routes created today.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_overview(self) -> DashboardOverview:
        # A real `date` object (not `.isoformat()`) so SQLAlchemy binds it as
        # DATE — Postgres rejects `date(created_at) = <text>` with an
        # UndefinedFunctionError since func.date()'s return type isn't
        # inferred, so the comparison's bind type comes from this literal.
        today = date.today()
        now_time = datetime.now(UTC).time()

        deliveries_today = (
            await self.session.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(func.date(Delivery.created_at) == today)
            )
            or 0
        )

        active_drivers = (
            await self.session.scalar(
                select(func.count()).select_from(Driver).where(Driver.status == "active")
            )
            or 0
        )

        total_distance_km = (
            await self.session.scalar(
                select(func.coalesce(func.sum(Route.total_distance_km), 0.0)).where(
                    func.date(Route.created_at) == today
                )
            )
            or 0.0
        )

        late_deliveries = (
            await self.session.scalar(
                select(func.count())
                .select_from(RouteStop)
                .join(Route, Route.id == RouteStop.route_id)
                .where(
                    func.date(Route.created_at) == today,
                    RouteStop.status != "completed",
                    RouteStop.estimated_arrival < now_time,
                )
            )
            or 0
        )

        return DashboardOverview(
            deliveries_today=deliveries_today,
            active_drivers=active_drivers,
            total_distance_km=round(total_distance_km, 1),
            late_deliveries=late_deliveries,
        )
