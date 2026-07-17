"""Builds an OR-Tools-ready RoutingProblem from domain entities (deliveries, drivers, vehicles)."""

from datetime import time

from app.db.models.delivery import Delivery
from app.db.models.depot import Depot
from app.db.models.driver import Driver
from app.db.models.vehicle import Vehicle
from app.services.route_optimizer.models import (
    DROP_PENALTY_BY_PRIORITY,
    LATE_PENALTY_BY_PRIORITY,
    RoutingProblem,
    Stop,
    TimeWindow,
    VehicleSpec,
)


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def build_routing_problem(
    deliveries: list[Delivery],
    vehicles: list[Vehicle],
    drivers_by_id: dict[str, Driver],
    depot: Depot,
    return_to_depot: bool,
) -> RoutingProblem:
    """Translate persisted domain entities into a solver-ready RoutingProblem."""
    if not vehicles:
        raise ValueError("At least one vehicle is required")
    if not deliveries:
        raise ValueError("At least one delivery is required")

    vehicle_specs: list[VehicleSpec] = []
    for vehicle in vehicles:
        driver = drivers_by_id[str(vehicle.driver_id)]
        working_hours = TimeWindow(
            start_minutes=_time_to_minutes(driver.working_hours_start),
            end_minutes=_time_to_minutes(driver.working_hours_end),
        )
        break_window = (
            TimeWindow(
                start_minutes=_time_to_minutes(driver.break_start),
                end_minutes=_time_to_minutes(driver.break_end),
            )
            if driver.break_start and driver.break_end
            else None
        )
        vehicle_specs.append(
            VehicleSpec(
                id=str(vehicle.id),
                driver_id=str(driver.id),
                capacity_weight_grams=round(vehicle.capacity_weight_kg * 1000),
                capacity_volume_ml=round(vehicle.capacity_volume_m3 * 1_000_000),
                working_hours=working_hours,
                break_window=break_window,
                max_working_minutes=driver.max_working_minutes,
            )
        )

    stops: list[Stop] = []
    for delivery in deliveries:
        time_window = (
            TimeWindow(
                start_minutes=_time_to_minutes(delivery.delivery_window_start),
                end_minutes=_time_to_minutes(delivery.delivery_window_end),
            )
            if delivery.delivery_window_start and delivery.delivery_window_end
            else None
        )
        priority_key = delivery.priority.value
        stops.append(
            Stop(
                id=str(delivery.id),
                latitude=delivery.latitude,
                longitude=delivery.longitude,
                demand_weight_grams=round(delivery.weight_kg * 1000),
                demand_volume_ml=round(delivery.volume_m3 * 1_000_000),
                service_minutes=delivery.unloading_minutes,
                time_window=time_window,
                late_penalty=LATE_PENALTY_BY_PRIORITY[priority_key],
                drop_penalty=DROP_PENALTY_BY_PRIORITY[priority_key],
            )
        )

    return RoutingProblem(
        stops=stops,
        vehicles=vehicle_specs,
        depot_latitude=depot.latitude,
        depot_longitude=depot.longitude,
        return_to_depot=return_to_depot,
    )
