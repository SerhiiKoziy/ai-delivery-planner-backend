"""Constraint builders applied to the OR-Tools routing model.

Each function is a pure operation on an already-constructed `routing`
(RoutingModel) / `manager` (RoutingIndexManager) pair, plus the domain
`RoutingProblem`. Node indexing convention used throughout: node 0 is
always the depot; nodes 1..len(stops) correspond to
`problem.stops[0..len(stops)-1]` in order.
"""

from app.services.route_optimizer.models import HORIZON_MINUTES, RoutingProblem


def apply_time_window_constraints(routing, manager, time_dimension, problem: RoutingProblem) -> None:
    """Soft time windows: arriving early just waits (no penalty); arriving after
    the window's end incurs a priority-scaled penalty rather than being infeasible
    — spec: 'якщо приїхав раніше — чекає, якщо запізнився — отримує штраф.'"""
    for stop_index, stop in enumerate(problem.stops, start=1):  # node 0 is the depot
        index = manager.NodeToIndex(stop_index)
        if stop.time_window is not None:
            time_dimension.CumulVar(index).SetRange(stop.time_window.start_minutes, HORIZON_MINUTES)
            time_dimension.SetCumulVarSoftUpperBound(index, stop.time_window.end_minutes, stop.late_penalty)
        # else: no window — leave the full [0, HORIZON_MINUTES] default range, no soft bound.


def apply_capacity_constraints(routing, manager, problem: RoutingProblem) -> None:
    """Two independent capacity dimensions: weight (grams) and volume (mL)."""
    weight_demand = [0] + [s.demand_weight_grams for s in problem.stops]
    volume_demand = [0] + [s.demand_volume_ml for s in problem.stops]

    def make_demand_callback(demands):
        def callback(from_index):
            node = manager.IndexToNode(from_index)
            return demands[node]

        return callback

    weight_callback_index = routing.RegisterUnaryTransitCallback(make_demand_callback(weight_demand))
    routing.AddDimensionWithVehicleCapacity(
        weight_callback_index, 0, [v.capacity_weight_grams for v in problem.vehicles], True, "Weight"
    )
    volume_callback_index = routing.RegisterUnaryTransitCallback(make_demand_callback(volume_demand))
    routing.AddDimensionWithVehicleCapacity(
        volume_callback_index, 0, [v.capacity_volume_ml for v in problem.vehicles], True, "Volume"
    )


def apply_working_hours_constraints(routing, manager, time_dimension, problem: RoutingProblem) -> None:
    """Each vehicle's route must start no earlier than its driver's shift start,
    end no later than shift end, and span no more than max_working_minutes."""
    for vehicle_id, vehicle in enumerate(problem.vehicles):
        start_index = routing.Start(vehicle_id)
        end_index = routing.End(vehicle_id)
        time_dimension.CumulVar(start_index).SetRange(
            vehicle.working_hours.start_minutes, vehicle.working_hours.start_minutes
        )
        time_dimension.CumulVar(end_index).SetRange(
            vehicle.working_hours.start_minutes, vehicle.working_hours.end_minutes
        )
        routing.solver().Add(
            time_dimension.CumulVar(end_index) - time_dimension.CumulVar(start_index)
            <= vehicle.max_working_minutes
        )
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start_index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))


def apply_drop_penalties(routing, manager, problem: RoutingProblem) -> None:
    """Let the solver drop a stop entirely (rather than fail to find any solution)
    if it's truly infeasible to serve everyone — at a steep, priority-scaled cost."""
    for stop_index, stop in enumerate(problem.stops, start=1):
        index = manager.NodeToIndex(stop_index)
        routing.AddDisjunction([index], stop.drop_penalty)


def apply_break_constraints(routing, manager, time_dimension, problem: RoutingProblem, service_minutes_by_node) -> None:
    """Best-effort hard lunch-break scheduling via OR-Tools' break-interval API.
    If this proves unreliable, the caller (solver.py) catches and degrades
    gracefully — breaks just won't be hard-enforced in that case."""
    solver = routing.solver()
    node_visit_transit = [service_minutes_by_node[manager.IndexToNode(i)] for i in range(routing.Size())]
    for vehicle_id, vehicle in enumerate(problem.vehicles):
        if vehicle.break_window is None:
            continue
        duration = vehicle.break_window.end_minutes - vehicle.break_window.start_minutes
        break_interval = solver.FixedDurationIntervalVar(
            vehicle.break_window.start_minutes,
            vehicle.break_window.start_minutes,
            duration,
            False,
            f"Break_{vehicle_id}",
        )
        time_dimension.SetBreakIntervalsOfVehicle([break_interval], vehicle_id, node_visit_transit)
