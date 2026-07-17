"""Pure unit tests for the route optimizer — no API, no DB.

Covers the haversine distance helper, the distance/duration matrix builder,
the RoutingProblem builder (translation from ORM entities), and a couple of
solver smoke tests exercising OR-Tools directly.
"""

import uuid
from datetime import time

import pytest

from app.db.models.delivery import Delivery, DeliveryPriority
from app.db.models.depot import Depot
from app.db.models.driver import Driver
from app.db.models.vehicle import Vehicle
from app.services.route_optimizer.builder import build_routing_problem
from app.services.route_optimizer.distance import build_distance_duration_matrix, haversine_km
from app.services.route_optimizer.mapper import map_solution
from app.services.route_optimizer.models import (
    DROP_PENALTY_BY_PRIORITY,
    LATE_PENALTY_BY_PRIORITY,
    RoutingProblem,
    Stop,
    TimeWindow,
    VehicleSpec,
)
from app.services.route_optimizer.solver import RouteSolver


# ---------------------------------------------------------------------------
# distance.py
# ---------------------------------------------------------------------------


def test_haversine_km_is_zero_for_identical_points() -> None:
    assert haversine_km(50.45, 30.52, 50.45, 30.52) == pytest.approx(0.0, abs=1e-9)


def test_haversine_km_is_symmetric() -> None:
    a = haversine_km(50.45, 30.52, 50.40, 30.60)
    b = haversine_km(50.40, 30.60, 50.45, 30.52)
    assert a == pytest.approx(b, abs=1e-9)


def test_haversine_km_one_degree_latitude_is_about_111km() -> None:
    km = haversine_km(50.0, 30.0, 51.0, 30.0)
    assert km == pytest.approx(111.0, rel=0.02)


def test_build_distance_duration_matrix_is_square_symmetric_zero_diagonal() -> None:
    coordinates = [(50.45, 30.52), (50.40, 30.60), (50.50, 30.40), (50.30, 30.70)]
    distance_matrix, duration_matrix = build_distance_duration_matrix(coordinates)

    n = len(coordinates)
    assert len(distance_matrix) == n
    assert len(duration_matrix) == n
    for row in distance_matrix + duration_matrix:
        assert len(row) == n

    for i in range(n):
        assert distance_matrix[i][i] == 0
        assert duration_matrix[i][i] == 0
        for j in range(n):
            assert distance_matrix[i][j] == distance_matrix[j][i]
            assert duration_matrix[i][j] == duration_matrix[j][i]
            assert isinstance(distance_matrix[i][j], int)
            assert isinstance(duration_matrix[i][j], int)


# ---------------------------------------------------------------------------
# builder.py
# ---------------------------------------------------------------------------


def _make_driver(**overrides) -> Driver:
    fields = {
        "id": uuid.uuid4(),
        "name": "Driver",
        "phone": "+380000000000",
        "working_hours_start": time(8, 0),
        "working_hours_end": time(18, 0),
        "break_start": time(13, 0),
        "break_end": time(14, 0),
        "max_working_minutes": 600,
    }
    fields.update(overrides)
    return Driver(**fields)


def _make_vehicle(driver_id, **overrides) -> Vehicle:
    fields = {
        "id": uuid.uuid4(),
        "plate_number": "AA1234BB",
        "capacity_weight_kg": 500.0,
        "capacity_volume_m3": 10.0,
        "driver_id": driver_id,
    }
    fields.update(overrides)
    return Vehicle(**fields)


def _make_delivery(**overrides) -> Delivery:
    fields = {
        "id": uuid.uuid4(),
        "customer_name": "Customer",
        "address": "Kyiv",
        "priority": DeliveryPriority.NORMAL,
        "unloading_minutes": 10,
        "weight_kg": 2.5,
        "volume_m3": 0.05,
        "latitude": 50.45,
        "longitude": 30.52,
    }
    fields.update(overrides)
    return Delivery(**fields)


def test_build_routing_problem_stop_count_and_capacity_scaling() -> None:
    driver = _make_driver()
    vehicle = _make_vehicle(driver.id, capacity_weight_kg=500.0, capacity_volume_m3=2.0)
    drivers_by_id = {str(driver.id): driver}
    depot = Depot(id=uuid.uuid4(), address="Depot", latitude=50.0, longitude=30.0)

    deliveries = [
        _make_delivery(weight_kg=10.0, volume_m3=0.5),
        _make_delivery(weight_kg=20.0, volume_m3=1.5),
    ]

    problem = build_routing_problem(deliveries, [vehicle], drivers_by_id, depot, True)

    assert len(problem.stops) == 2
    assert problem.stops[0].demand_weight_grams == 10_000
    assert problem.stops[0].demand_volume_ml == 500_000
    assert problem.stops[1].demand_weight_grams == 20_000
    assert problem.stops[1].demand_volume_ml == 1_500_000
    assert len(problem.vehicles) == 1
    assert problem.vehicles[0].capacity_weight_grams == 500_000
    assert problem.vehicles[0].capacity_volume_ml == 2_000_000
    assert problem.return_to_depot is True


def test_build_routing_problem_time_window_conversion() -> None:
    driver = _make_driver(
        working_hours_start=time(7, 30), working_hours_end=time(19, 15), break_start=None, break_end=None
    )
    vehicle = _make_vehicle(driver.id)
    drivers_by_id = {str(driver.id): driver}
    depot = Depot(id=uuid.uuid4(), address="Depot", latitude=50.0, longitude=30.0)

    delivery_with_window = _make_delivery(
        delivery_window_start=time(9, 0), delivery_window_end=time(11, 30)
    )
    delivery_without_window = _make_delivery()

    problem = build_routing_problem(
        [delivery_with_window, delivery_without_window], [vehicle], drivers_by_id, depot, True
    )

    with_window_stop = next(s for s in problem.stops if s.id == str(delivery_with_window.id))
    without_window_stop = next(s for s in problem.stops if s.id == str(delivery_without_window.id))

    assert with_window_stop.time_window == TimeWindow(start_minutes=9 * 60, end_minutes=11 * 60 + 30)
    assert without_window_stop.time_window is None

    assert problem.vehicles[0].working_hours == TimeWindow(
        start_minutes=7 * 60 + 30, end_minutes=19 * 60 + 15
    )
    assert problem.vehicles[0].break_window is None


def test_build_routing_problem_penalty_lookup_by_priority() -> None:
    driver = _make_driver()
    vehicle = _make_vehicle(driver.id)
    drivers_by_id = {str(driver.id): driver}
    depot = Depot(id=uuid.uuid4(), address="Depot", latitude=50.0, longitude=30.0)

    deliveries = [
        _make_delivery(priority=DeliveryPriority.LOW),
        _make_delivery(priority=DeliveryPriority.HIGH),
        _make_delivery(priority=DeliveryPriority.VIP),
    ]

    problem = build_routing_problem(deliveries, [vehicle], drivers_by_id, depot, True)

    by_id = {s.id: s for s in problem.stops}
    assert by_id[str(deliveries[0].id)].late_penalty == LATE_PENALTY_BY_PRIORITY["low"]
    assert by_id[str(deliveries[0].id)].drop_penalty == DROP_PENALTY_BY_PRIORITY["low"]
    assert by_id[str(deliveries[1].id)].late_penalty == LATE_PENALTY_BY_PRIORITY["high"]
    assert by_id[str(deliveries[2].id)].drop_penalty == DROP_PENALTY_BY_PRIORITY["vip"]


def test_build_routing_problem_requires_vehicles_and_deliveries() -> None:
    driver = _make_driver()
    vehicle = _make_vehicle(driver.id)
    drivers_by_id = {str(driver.id): driver}
    depot = Depot(id=uuid.uuid4(), address="Depot", latitude=50.0, longitude=30.0)
    delivery = _make_delivery()

    with pytest.raises(ValueError, match="vehicle"):
        build_routing_problem([delivery], [], drivers_by_id, depot, True)

    with pytest.raises(ValueError, match="delivery"):
        build_routing_problem([], [vehicle], drivers_by_id, depot, True)


# ---------------------------------------------------------------------------
# solver.py + mapper.py smoke tests (hand-built RoutingProblem, no DB)
# ---------------------------------------------------------------------------


def _hand_built_vehicle(**overrides) -> VehicleSpec:
    fields = {
        "id": str(uuid.uuid4()),
        "driver_id": str(uuid.uuid4()),
        "capacity_weight_grams": 1_000_000,
        "capacity_volume_ml": 10_000_000,
        "working_hours": TimeWindow(start_minutes=8 * 60, end_minutes=20 * 60),
        "break_window": None,
        "max_working_minutes": 600,
    }
    fields.update(overrides)
    return VehicleSpec(**fields)


def _hand_built_stop(lat: float, lng: float, **overrides) -> Stop:
    fields = {
        "id": str(uuid.uuid4()),
        "latitude": lat,
        "longitude": lng,
        "demand_weight_grams": 1000,
        "demand_volume_ml": 1000,
        "service_minutes": 5,
        "time_window": None,
        "late_penalty": LATE_PENALTY_BY_PRIORITY["normal"],
        "drop_penalty": DROP_PENALTY_BY_PRIORITY["normal"],
    }
    fields.update(overrides)
    return Stop(**fields)


def test_solver_smoke_all_stops_assigned_with_generous_constraints() -> None:
    stops = [
        _hand_built_stop(50.45, 30.52),
        _hand_built_stop(50.46, 30.53),
        _hand_built_stop(50.44, 30.51),
        _hand_built_stop(50.45, 30.50),
    ]
    vehicles = [_hand_built_vehicle(), _hand_built_vehicle()]
    problem = RoutingProblem(
        stops=stops, vehicles=vehicles, depot_latitude=50.45, depot_longitude=30.52
    )

    solver = RouteSolver(problem)
    solver.build_model()
    result = solver.solve()

    assert result.assignment is not None

    mapped = map_solution(result, problem, solver.distance_matrix)
    assert mapped.unassigned_stop_ids == []
    all_mapped_ids = {s.stop_id for route in mapped.routes for s in route.stops}
    assert all_mapped_ids == {s.id for s in stops}


def test_solver_drops_stop_instead_of_failing_on_conflicting_windows() -> None:
    # One vehicle, two stops far apart with tight, non-overlapping time windows
    # that cannot both be honored given travel time — the solver should drop
    # one of them via the disjunction penalty rather than return no solution.
    stops = [
        _hand_built_stop(
            50.45, 30.52, time_window=TimeWindow(start_minutes=9 * 60, end_minutes=9 * 60 + 5)
        ),
        _hand_built_stop(
            52.00, 32.00, time_window=TimeWindow(start_minutes=9 * 60, end_minutes=9 * 60 + 5)
        ),
    ]
    vehicles = [_hand_built_vehicle(max_working_minutes=60)]
    problem = RoutingProblem(
        stops=stops, vehicles=vehicles, depot_latitude=50.45, depot_longitude=30.52
    )

    solver = RouteSolver(problem)
    solver.build_model()
    result = solver.solve()

    assert result.assignment is not None
