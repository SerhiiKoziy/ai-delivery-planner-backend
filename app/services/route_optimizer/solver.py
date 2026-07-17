"""OR-Tools routing solver wrapper."""

from app.services.route_optimizer.models import RoutingProblem


class RouteSolver:
    """Wraps google.ortools.constraint_solver.routing to solve a RoutingProblem."""

    def __init__(self, problem: RoutingProblem) -> None:
        self.problem = problem

    def build_model(self) -> None:
        """Construct the OR-Tools index manager and routing model."""
        raise NotImplementedError

    def solve(self):
        """Run the solver and return the raw OR-Tools assignment/solution."""
        raise NotImplementedError
