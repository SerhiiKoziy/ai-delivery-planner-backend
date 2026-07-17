"""OR-Tools routing solver wrapper for a RoutingProblem."""

import logging
from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.services.route_optimizer.constraints import (
    apply_break_constraints,
    apply_capacity_constraints,
    apply_drop_penalties,
    apply_time_window_constraints,
    apply_working_hours_constraints,
)
from app.services.route_optimizer.distance import build_distance_duration_matrix
from app.services.route_optimizer.models import HORIZON_MINUTES, RoutingProblem

logger = logging.getLogger(__name__)


@dataclass
class SolveResult:
    assignment: object  # the raw OR-Tools Assignment, or None if infeasible
    routing: object  # the RoutingModel (needed by the mapper)
    manager: object  # the RoutingIndexManager (needed by the mapper)
    time_dimension: object  # routing.GetDimensionOrDie("Time") (needed by the mapper)


class RouteSolver:
    """Wraps ortools.constraint_solver.pywrapcp to solve a RoutingProblem."""

    def __init__(self, problem: RoutingProblem) -> None:
        self.problem = problem
        self.manager = None
        self.routing = None
        self.distance_matrix = None
        self.duration_matrix = None
        self.time_dimension = None

    def build_model(self) -> None:
        problem = self.problem
        coordinates = [(problem.depot_latitude, problem.depot_longitude)] + [
            (s.latitude, s.longitude) for s in problem.stops
        ]
        self.distance_matrix, self.duration_matrix = build_distance_duration_matrix(coordinates)

        num_nodes = len(coordinates)
        num_vehicles = len(problem.vehicles)
        self.manager = pywrapcp.RoutingIndexManager(num_nodes, num_vehicles, 0)
        self.routing = pywrapcp.RoutingModel(self.manager)

        # distance callback -> arc cost
        def distance_callback(from_index, to_index):
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)
            if not problem.return_to_depot and to_node == 0:
                return 0
            return self.distance_matrix[from_node][to_node]

        distance_callback_index = self.routing.RegisterTransitCallback(distance_callback)
        self.routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)

        # time callback (travel + service time at the FROM node) -> "Time" dimension
        service_minutes_by_node = [0] + [s.service_minutes for s in problem.stops]

        def time_callback(from_index, to_index):
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)
            travel = 0 if (not problem.return_to_depot and to_node == 0) else self.duration_matrix[from_node][to_node]
            return travel + service_minutes_by_node[from_node]

        time_callback_index = self.routing.RegisterTransitCallback(time_callback)
        self.routing.AddDimension(
            time_callback_index,
            HORIZON_MINUTES,  # slack_max — allow waiting for a time window anywhere up to a full day
            HORIZON_MINUTES,  # max cumulative value
            False,  # do NOT force start cumul to zero — vehicles start at their own working_hours_start
            "Time",
        )
        time_dimension = self.routing.GetDimensionOrDie("Time")

        apply_time_window_constraints(self.routing, self.manager, time_dimension, problem)
        apply_capacity_constraints(self.routing, self.manager, problem)
        apply_working_hours_constraints(self.routing, self.manager, time_dimension, problem)
        apply_drop_penalties(self.routing, self.manager, problem)
        try:
            apply_break_constraints(self.routing, self.manager, time_dimension, problem, service_minutes_by_node)
        except Exception:
            # Best-effort: hard break-interval scheduling is the trickiest part of
            # the OR-Tools API surface here. If it can't be wired reliably, degrade
            # gracefully rather than making the whole solver unusable — breaks
            # just won't be hard-enforced in that case.
            logger.warning("Break constraints could not be applied", exc_info=True)

        self.time_dimension = time_dimension

    def solve(self) -> SolveResult:
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.FromSeconds(5)

        assignment = self.routing.SolveWithParameters(search_parameters)
        return SolveResult(
            assignment=assignment,
            routing=self.routing,
            manager=self.manager,
            time_dimension=self.time_dimension,
        )
