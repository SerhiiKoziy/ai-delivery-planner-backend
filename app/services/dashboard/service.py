"""Dashboard overview and usage-history: aggregate operational stats from
current DB state."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.delivery import Delivery
from app.db.models.driver import Driver
from app.db.models.route import Route
from app.db.models.route_stop import RouteStop
from app.db.models.vehicle import Vehicle
from app.schemas.dashboard import DailyUsagePoint, DashboardOverview, DashboardUsageHistory


class DashboardService:
    """Computes headline dashboard metrics from current DB state.

    "Today" and "late" are approximations: the schema has no explicit
    delivery-date or actual-arrival column yet (see TODOs on the Delivery/
    RouteStop models), so today's activity is inferred from `created_at`,
    and lateness from `estimated_arrival` (a time-of-day, not a timestamp)
    versus the current time for stops on routes created today.
    """

    def __init__(self, session: AsyncSession, organization_id) -> None:
        self.session = session
        self.organization_id = organization_id

    async def get_overview(self) -> DashboardOverview:
        # UTC `date`, not `date.today()` (which is local-timezone) — every
        # `created_at` in this schema is stored via `datetime.now(UTC)`, so
        # comparing against the local calendar date is off by one near
        # midnight UTC whenever the server's local timezone is ahead of UTC.
        # Kept as a real `date` object (not `.isoformat()`) so SQLAlchemy
        # binds it as DATE — Postgres rejects `date(created_at) = <text>`
        # with an UndefinedFunctionError since func.date()'s return type
        # isn't inferred, so the comparison's bind type comes from this
        # literal.
        now = datetime.now(UTC)
        today = now.date()
        now_time = now.time()

        deliveries_today = (
            await self.session.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(
                    Delivery.organization_id == self.organization_id,
                    func.date(Delivery.created_at) == today,
                )
            )
            or 0
        )

        active_drivers = (
            await self.session.scalar(
                select(func.count())
                .select_from(Driver)
                .where(Driver.organization_id == self.organization_id, Driver.status == "active")
            )
            or 0
        )

        active_vehicles = (
            await self.session.scalar(
                select(func.count())
                .select_from(Vehicle)
                .where(
                    Vehicle.organization_id == self.organization_id, Vehicle.status == "active"
                )
            )
            or 0
        )

        total_distance_km = (
            await self.session.scalar(
                select(func.coalesce(func.sum(Route.total_distance_km), 0.0)).where(
                    Route.organization_id == self.organization_id,
                    func.date(Route.created_at) == today,
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
                    Route.organization_id == self.organization_id,
                    func.date(Route.created_at) == today,
                    RouteStop.status != "completed",
                    RouteStop.estimated_arrival < now_time,
                )
            )
            or 0
        )

        drivers_on_route_today = (
            await self.session.scalar(
                select(func.count(func.distinct(Route.driver_id))).where(
                    Route.organization_id == self.organization_id,
                    func.date(Route.created_at) == today,
                    Route.driver_id.is_not(None),
                )
            )
            or 0
        )

        vehicles_in_use_today = (
            await self.session.scalar(
                select(func.count(func.distinct(Route.vehicle_id))).where(
                    Route.organization_id == self.organization_id,
                    func.date(Route.created_at) == today,
                    Route.vehicle_id.is_not(None),
                )
            )
            or 0
        )

        return DashboardOverview(
            deliveries_today=deliveries_today,
            active_drivers=active_drivers,
            total_distance_km=round(total_distance_km, 1),
            late_deliveries=late_deliveries,
            active_vehicles=active_vehicles,
            drivers_on_route_today=drivers_on_route_today,
            drivers_idle_today=max(active_drivers - drivers_on_route_today, 0),
            vehicles_in_use_today=vehicles_in_use_today,
            vehicles_available_today=max(active_vehicles - vehicles_in_use_today, 0),
        )

    async def get_usage_history(self, days: int = 30) -> DashboardUsageHistory:
        """Return a zero-filled, day-bucketed usage series for the last
        `days` days (inclusive of today, UTC), built from existing
        `Delivery`/`Route` rows — there is no separate per-request usage
        log, so this approximates "usage" via domain events that already
        carry a `created_at` timestamp.
        """
        today = datetime.now(UTC).date()
        start_date = today - timedelta(days=days - 1)

        # `type_=Date` is required, not cosmetic: without it, `func.date(...)`
        # has no declared result type, so SQLite (which has no native DATE
        # type) returns the grouped column as a plain string instead of a
        # `date` object — the dict keys below would then never match
        # `start_date + timedelta(...)`, silently zero-filling everything.
        delivery_day = func.date(Delivery.created_at, type_=Date)
        route_day = func.date(Route.created_at, type_=Date)

        deliveries_by_day = dict(
            (
                await self.session.execute(
                    select(delivery_day.label("day"), func.count().label("count"))
                    .where(
                        Delivery.organization_id == self.organization_id,
                        delivery_day >= start_date,
                    )
                    .group_by(delivery_day)
                )
            ).all()
        )

        routes_by_day = {
            row.day: (row.routes_count, row.distance_km)
            for row in (
                await self.session.execute(
                    select(
                        route_day.label("day"),
                        func.count().label("routes_count"),
                        func.coalesce(func.sum(Route.total_distance_km), 0.0).label(
                            "distance_km"
                        ),
                    )
                    .where(
                        Route.organization_id == self.organization_id,
                        route_day >= start_date,
                    )
                    .group_by(route_day)
                )
            ).all()
        }

        points = []
        for offset in range(days):
            day = start_date + timedelta(days=offset)
            routes_count, distance_km = routes_by_day.get(day, (0, 0.0))
            points.append(
                DailyUsagePoint(
                    date=day,
                    deliveries_count=deliveries_by_day.get(day, 0),
                    routes_generated=routes_count,
                    distance_km=round(distance_km, 1),
                )
            )

        return DashboardUsageHistory(points=points)
