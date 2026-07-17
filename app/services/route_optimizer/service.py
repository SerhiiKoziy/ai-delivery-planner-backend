"""Route optimizer orchestration: wires repositories, the RoutingProblem
builder, the OR-Tools solver, and the solution mapper together, then
persists the resulting Route/RouteStop rows.
"""

import uuid
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.route import Route
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
