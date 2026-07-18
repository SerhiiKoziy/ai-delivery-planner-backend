"""Route optimizer orchestration: wires repositories, the RoutingProblem
builder, the OR-Tools solver, and the solution mapper together, then
persists the resulting Route/RouteStop rows.
"""

import copy
import uuid
from dataclasses import dataclass
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.route import Route
from app.db.models.route_stop import RouteStop
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.depot_repository import DepotRepository
from app.repositories.driver_repository import DriverRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.route import OptimizeRequest, OptimizeResult, RouteRead, RouteStopRead
from app.services.route_optimizer.builder import build_routing_problem
from app.services.route_optimizer.mapper import map_solution
from app.services.route_optimizer.solver import RouteSolver


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


@dataclass
class ReplanOutcome:
    """Result of `RouteOptimizerService.replan()`.

    `route` is either the freshly-refetched persisted Route (persist=True) or
    a detached in-memory copy of the original Route annotated with the totals
    that WOULD have been persisted (persist=False, dry run) — never the same
    object as a DB-attached row in the dry-run case, so callers can't
    accidentally believe an un-persisted mutation is real.
    """

    route: Route
    stops_before: list[RouteStop]
    stops_after: list[RouteStopRead]
    unassigned_delivery_ids: list[uuid.UUID]


class RouteOptimizerService:
    """Application-level orchestration for the route optimizer vertical slice."""

    def __init__(
        self,
        delivery_repository: DeliveryRepository,
        vehicle_repository: VehicleRepository,
        driver_repository: DriverRepository,
        depot_repository: DepotRepository,
        route_repository: RouteRepository,
        route_stop_repository: RouteStopRepository,
        session: AsyncSession,
    ) -> None:
        self.delivery_repository = delivery_repository
        self.vehicle_repository = vehicle_repository
        self.driver_repository = driver_repository
        self.depot_repository = depot_repository
        self.route_repository = route_repository
        self.route_stop_repository = route_stop_repository
        self.session = session

    async def optimize(self, payload: OptimizeRequest) -> OptimizeResult:
        deliveries = await self.delivery_repository.get_many(payload.delivery_ids)
        geocoded = [d for d in deliveries if d.latitude is not None and d.longitude is not None]
        skipped_not_geocoded = [d.id for d in deliveries if d not in geocoded]

        vehicles = await self.vehicle_repository.get_many(payload.vehicle_ids)
        usable_vehicles = [v for v in vehicles if v.driver_id is not None]
        vehicles_without_driver = [v.id for v in vehicles if v.driver_id is None]

        driver_ids = [v.driver_id for v in usable_vehicles]
        drivers = await self.driver_repository.get_many(driver_ids) if driver_ids else []
        drivers_by_id = {str(d.id): d for d in drivers}

        depot = await self.depot_repository.get(payload.depot_id)
        if depot is None:
            raise ValueError("Depot not found")

        if not geocoded or not usable_vehicles:
            return OptimizeResult(
                routes=[],
                unassigned_delivery_ids=[d.id for d in geocoded],
                skipped_not_geocoded=skipped_not_geocoded,
                vehicles_without_driver=vehicles_without_driver,
            )

        problem = build_routing_problem(
            geocoded, usable_vehicles, drivers_by_id, depot, payload.return_to_depot
        )

        solver = RouteSolver(problem)
        solver.build_model()
        result = solver.solve()

        if result.assignment is None:
            raise ValueError("No feasible solution found for the given deliveries/vehicles")

        mapped = map_solution(result, problem, solver.distance_matrix)

        vehicles_by_id = {str(v.id): v for v in usable_vehicles}
        created_routes: list[RouteRead] = []
        for mapped_route in mapped.routes:
            vehicle = vehicles_by_id[mapped_route.vehicle_id]
            route_row = await self.route_repository.create(
                driver_id=vehicle.driver_id,
                vehicle_id=vehicle.id,
                depot_id=depot.id,
                return_to_depot=payload.return_to_depot,
                status="planned",
                total_distance_km=mapped_route.total_distance_meters / 1000,
                total_duration_minutes=mapped_route.total_duration_minutes,
            )

            for mapped_stop in mapped_route.stops:
                arrival = mapped_stop.arrival_minutes
                departure = mapped_stop.departure_minutes
                await self.route_stop_repository.create(
                    route_id=route_row.id,
                    delivery_id=uuid.UUID(mapped_stop.stop_id),
                    sequence=mapped_stop.sequence,
                    estimated_arrival=time(arrival // 60 % 24, arrival % 60),
                    estimated_departure=time(departure // 60 % 24, departure % 60),
                    distance_from_previous_km=mapped_stop.distance_from_previous_meters / 1000,
                )

            stops = await self.route_stop_repository.list_by_route(route_row.id)
            created_routes.append(
                RouteRead(
                    id=route_row.id,
                    driver_id=route_row.driver_id,
                    vehicle_id=route_row.vehicle_id,
                    depot_id=route_row.depot_id,
                    status=route_row.status,
                    return_to_depot=route_row.return_to_depot,
                    total_distance_km=route_row.total_distance_km,
                    total_duration_minutes=route_row.total_duration_minutes,
                    created_at=route_row.created_at,
                    updated_at=route_row.updated_at,
                    stops=[RouteStopRead.model_validate(s) for s in stops],
                )
            )

        unassigned_delivery_ids = [uuid.UUID(sid) for sid in mapped.unassigned_stop_ids]

        return OptimizeResult(
            routes=created_routes,
            unassigned_delivery_ids=unassigned_delivery_ids,
            skipped_not_geocoded=skipped_not_geocoded,
            vehicles_without_driver=vehicles_without_driver,
        )

    async def get_route(self, route_id: uuid.UUID) -> Route | None:
        return await self.route_repository.get(route_id)

    async def get_route_with_stops(self, route_id: uuid.UUID) -> tuple[Route, list] | None:
        route = await self.route_repository.get(route_id)
        if route is None:
            return None
        stops = await self.route_stop_repository.list_by_route(route_id)
        return route, stops

    async def replan(
        self,
        route_id: uuid.UUID,
        *,
        excluded_delivery_ids: list[uuid.UUID] | None = None,
        window_overrides: dict[uuid.UUID, tuple[time | None, time | None]] | None = None,
        start_delay_minutes: int = 0,
        persist: bool = True,
    ) -> ReplanOutcome:
        """Re-run the optimizer over a route's still-pending stops only.

        Stops that are no longer "pending" (i.e. already completed or
        skipped) are preserved as-is; only pending stops are candidates for
        re-optimization, minus any explicitly excluded deliveries. Per-delivery
        time-window overrides and a driver start-delay can be applied to the
        solver input for this run only, without mutating persisted state,
        unless `persist=True` in which case the resulting plan (and any window
        overrides) are written back to the DB.
        """
        route = await self.route_repository.get(route_id)
        if route is None:
            raise ValueError("Route not found")

        # Snapshot BEFORE any mutation.
        stops_before = await self.route_stop_repository.list_by_route(route_id)

        preserved_stops = [s for s in stops_before if s.status != "pending"]
        pending_stops = [s for s in stops_before if s.status == "pending"]

        excluded_delivery_ids = excluded_delivery_ids or []
        window_overrides = window_overrides or {}

        pending_delivery_ids = [
            s.delivery_id for s in pending_stops if s.delivery_id not in excluded_delivery_ids
        ]

        # sequence_offset is the highest sequence already in use by a preserved
        # stop (-1 if there are none), so the first newly-optimized stop lands
        # at sequence_offset + 1 with no collision or gap against preserved
        # stops, and — when there are no preserved stops at all — new stops
        # still start at 0, matching optimize()'s own numbering.
        sequence_offset = max((s.sequence for s in preserved_stops), default=-1)

        if not pending_delivery_ids:
            # Nothing left to re-optimize (e.g. every remaining delivery was
            # excluded/cancelled) — skip the solver entirely.
            stops_after = sorted(
                (RouteStopRead.model_validate(s) for s in preserved_stops),
                key=lambda s: s.sequence,
            )
            if persist and pending_stops:
                await self.route_stop_repository.delete_by_ids([s.id for s in pending_stops])
            return ReplanOutcome(
                route=route,
                stops_before=stops_before,
                stops_after=stops_after,
                unassigned_delivery_ids=[],
            )

        deliveries = await self.delivery_repository.get_many(pending_delivery_ids)

        # Working copies for solver input only — never the session-tracked
        # originals — so a dry run (persist=False) can never leak a mutation
        # into the DB via autoflush before we've decided whether to persist.
        working_deliveries = []
        for delivery in deliveries:
            override = window_overrides.get(delivery.id)
            if override is None:
                working_deliveries.append(delivery)
                continue
            window_start, window_end = override
            working_delivery = copy.copy(delivery)
            working_delivery.delivery_window_start = window_start
            working_delivery.delivery_window_end = window_end
            working_deliveries.append(working_delivery)
            if persist:
                await self.delivery_repository.update(
                    delivery.id,
                    delivery_window_start=window_start,
                    delivery_window_end=window_end,
                )

        if route.vehicle_id is None:
            raise ValueError("Route has no assigned vehicle")
        vehicle = await self.vehicle_repository.get(route.vehicle_id)
        if vehicle is None:
            raise ValueError("Route has no assigned vehicle")

        if vehicle.driver_id is None:
            raise ValueError("Route has no assigned driver")
        driver = await self.driver_repository.get(vehicle.driver_id)
        if driver is None:
            raise ValueError("Route has no assigned driver")

        depot = await self.depot_repository.get(route.depot_id)
        if depot is None:
            raise ValueError("Depot not found")

        # In-memory-only driver shift for solver input — never persisted.
        solver_driver = driver
        if start_delay_minutes > 0:
            solver_driver = copy.copy(driver)
            shifted_start_minutes = min(
                _time_to_minutes(driver.working_hours_start) + start_delay_minutes,
                _time_to_minutes(driver.working_hours_end),
            )
            solver_driver.working_hours_start = time(
                shifted_start_minutes // 60 % 24, shifted_start_minutes % 60
            )

        problem = build_routing_problem(
            working_deliveries, [vehicle], {str(driver.id): solver_driver}, depot, route.return_to_depot
        )
        solver = RouteSolver(problem)
        solver.build_model()
        result = solver.solve()

        if result.assignment is None:
            raise ValueError("No feasible solution found for the given deliveries/vehicle")

        mapped = map_solution(result, problem, solver.distance_matrix)
        mapped_route = mapped.routes[0] if mapped.routes else None
        mapped_stops = mapped_route.stops if mapped_route is not None else []
        new_distance_meters = mapped_route.total_distance_meters if mapped_route is not None else 0
        new_duration_minutes = mapped_route.total_duration_minutes if mapped_route is not None else 0
        unassigned_delivery_ids = [uuid.UUID(sid) for sid in mapped.unassigned_stop_ids]

        total_distance_km = (
            sum(s.distance_from_previous_km for s in preserved_stops) + new_distance_meters / 1000
        )
        total_duration_minutes = (
            max((_time_to_minutes(s.estimated_departure) for s in preserved_stops), default=0)
            + new_duration_minutes
        )

        if persist:
            await self.route_stop_repository.delete_by_ids([s.id for s in pending_stops])
            for mapped_stop in mapped_stops:
                arrival = mapped_stop.arrival_minutes
                departure = mapped_stop.departure_minutes
                await self.route_stop_repository.create(
                    route_id=route.id,
                    delivery_id=uuid.UUID(mapped_stop.stop_id),
                    sequence=sequence_offset + 1 + mapped_stop.sequence,
                    estimated_arrival=time(arrival // 60 % 24, arrival % 60),
                    estimated_departure=time(departure // 60 % 24, departure % 60),
                    distance_from_previous_km=mapped_stop.distance_from_previous_meters / 1000,
                    status="pending",
                )

            await self.route_repository.update(
                route_id,
                total_distance_km=total_distance_km,
                total_duration_minutes=total_duration_minutes,
            )
            refreshed_route = await self.route_repository.get(route_id)
            all_stops = await self.route_stop_repository.list_by_route(route_id)

            return ReplanOutcome(
                route=refreshed_route,
                stops_before=stops_before,
                stops_after=[RouteStopRead.model_validate(s) for s in all_stops],
                unassigned_delivery_ids=unassigned_delivery_ids,
            )

        # Dry run: nothing above touched the DB (get_many/get calls are reads;
        # the delivery window-override branch above only calls .update() when
        # persist=True). Simulate the resulting stop list/route totals only.
        simulated_new_stops = [
            RouteStopRead(
                id=uuid.uuid4(),
                delivery_id=uuid.UUID(mapped_stop.stop_id),
                sequence=sequence_offset + 1 + mapped_stop.sequence,
                estimated_arrival=time(
                    mapped_stop.arrival_minutes // 60 % 24, mapped_stop.arrival_minutes % 60
                ),
                estimated_departure=time(
                    mapped_stop.departure_minutes // 60 % 24, mapped_stop.departure_minutes % 60
                ),
                distance_from_previous_km=mapped_stop.distance_from_previous_meters / 1000,
                status="pending",
            )
            for mapped_stop in mapped_stops
        ]
        stops_after = sorted(
            [RouteStopRead.model_validate(s) for s in preserved_stops] + simulated_new_stops,
            key=lambda s: s.sequence,
        )

        simulated_route = copy.copy(route)
        simulated_route.total_distance_km = total_distance_km
        simulated_route.total_duration_minutes = total_duration_minutes

        return ReplanOutcome(
            route=simulated_route,
            stops_before=stops_before,
            stops_after=stops_after,
            unassigned_delivery_ids=unassigned_delivery_ids,
        )
