"""Maps a solved OR-Tools assignment back to route/stop domain data."""

from dataclasses import dataclass

from app.services.route_optimizer.models import RoutingProblem


@dataclass
class MappedStop:
    stop_id: str  # Delivery UUID string, from RoutingProblem.stops
    sequence: int  # 0-indexed position within this vehicle's route
    arrival_minutes: int
    departure_minutes: int  # arrival + service_minutes
    distance_from_previous_meters: int


@dataclass
class MappedRoute:
    vehicle_id: str
    stops: list[MappedStop]
    total_distance_meters: int
    total_duration_minutes: int


@dataclass
class MappedSolution:
    routes: list[MappedRoute]  # only vehicles with >= 1 stop
    unassigned_stop_ids: list[str]


def map_solution(solve_result, problem: RoutingProblem, distance_matrix) -> MappedSolution:
    """`solve_result` is a `SolveResult` from solver.py (has .assignment/.routing/.manager/.time_dimension).
    Returns None-safe: caller must check `solve_result.assignment is not None` before calling this."""
    routing = solve_result.routing
    manager = solve_result.manager
    assignment = solve_result.assignment
    time_dimension = solve_result.time_dimension

    routes: list[MappedRoute] = []
    for vehicle_id, vehicle in enumerate(problem.vehicles):
        index = routing.Start(vehicle_id)
        stops: list[MappedStop] = []
        total_distance = 0
        sequence = 0
        previous_node = manager.IndexToNode(index)  # starts at the depot (node 0)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            next_index = assignment.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            if node != 0:  # skip the depot node itself
                stop = problem.stops[node - 1]
                arrival = assignment.Value(time_dimension.CumulVar(index))
                stops.append(
                    MappedStop(
                        stop_id=stop.id,
                        sequence=sequence,
                        arrival_minutes=arrival,
                        departure_minutes=arrival + stop.service_minutes,
                        distance_from_previous_meters=distance_matrix[previous_node][node],
                    )
                )
                sequence += 1
                previous_node = node
            # Mirror the arc-cost callback in solver.py: the leg back to the
            # depot is not a real drive when return_to_depot is False, so it
            # must not count toward the reported total distance either.
            if problem.return_to_depot or next_node != 0:
                total_distance += distance_matrix[node][next_node]
            index = next_index
        if stops:
            routes.append(
                MappedRoute(
                    vehicle_id=vehicle.id,
                    stops=stops,
                    total_distance_meters=total_distance,
                    total_duration_minutes=(
                        assignment.Value(time_dimension.CumulVar(routing.End(vehicle_id)))
                        - assignment.Value(time_dimension.CumulVar(routing.Start(vehicle_id)))
                    ),
                )
            )

    unassigned_stop_ids = []
    for node in range(1, len(problem.stops) + 1):
        index = manager.NodeToIndex(node)
        if assignment.Value(routing.NextVar(index)) == index:
            unassigned_stop_ids.append(problem.stops[node - 1].id)

    return MappedSolution(routes=routes, unassigned_stop_ids=unassigned_stop_ids)
