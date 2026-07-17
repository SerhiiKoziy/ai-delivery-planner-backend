"""Domain models representing an OR-Tools routing problem instance."""

from dataclasses import dataclass


@dataclass
class TimeWindow:
    """An allowed [start, end] arrival window, in minutes from the planning horizon start."""

    start_minutes: int
    end_minutes: int


@dataclass
class Stop:
    """A single delivery stop to be visited."""

    id: str
    latitude: float
    longitude: float
    demand: int
    time_window: TimeWindow | None
    priority: int = 0


@dataclass
class Vehicle:
    """A vehicle available for the routing problem."""

    id: str
    capacity: int
    working_hours: TimeWindow


@dataclass
class RoutingProblem:
    """Full input to the solver: stops, vehicles, and a shared depot."""

    stops: list[Stop]
    vehicles: list[Vehicle]
    depot_latitude: float
    depot_longitude: float
