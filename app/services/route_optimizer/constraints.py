"""Constraint builders applied to the OR-Tools routing model."""

from app.services.route_optimizer.models import RoutingProblem


def apply_time_window_constraints(routing, manager, problem: RoutingProblem) -> None:
    """Restrict each stop's arrival time to its configured time window."""
    raise NotImplementedError


def apply_capacity_constraints(routing, manager, problem: RoutingProblem) -> None:
    """Cap cumulative demand per vehicle to its capacity."""
    raise NotImplementedError


def apply_working_hours_constraints(routing, manager, problem: RoutingProblem) -> None:
    """Restrict each vehicle's total route span to its driver's working hours."""
    raise NotImplementedError
