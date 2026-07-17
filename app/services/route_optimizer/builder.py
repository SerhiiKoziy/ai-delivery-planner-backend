"""Builds an OR-Tools-ready RoutingProblem from domain entities (deliveries, drivers, vehicles)."""

from app.services.route_optimizer.models import RoutingProblem


def build_routing_problem(deliveries: list, drivers: list, vehicles: list) -> RoutingProblem:
    """Translate persisted domain entities into a solver-ready RoutingProblem."""
    raise NotImplementedError
