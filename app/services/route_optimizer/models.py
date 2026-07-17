"""Domain models representing an OR-Tools routing problem instance.

All time values are integer minutes since midnight (0-1439) — this lets
`datetime.time` fields on Driver/Delivery convert directly (hour*60+minute)
without needing a separate "planning horizon start" concept.
"""

from dataclasses import dataclass

HORIZON_MINUTES = 24 * 60


@dataclass
class TimeWindow:
    start_minutes: int
    end_minutes: int


@dataclass
class Stop:
    """A single delivery stop to be visited (index 0 in RoutingProblem.stops maps to node 1 — node 0 is always the depot)."""

    id: str  # the Delivery's UUID, as a string
    latitude: float
    longitude: float
    demand_weight_grams: int  # weight_kg * 1000, rounded — integer for OR-Tools capacity dimension
    demand_volume_ml: int  # volume_m3 * 1_000_000, rounded — integer for OR-Tools capacity dimension
    service_minutes: int
    time_window: TimeWindow | None  # None means "no constraint" (full-horizon window)
    late_penalty: int  # priority-scaled soft-upper-bound violation cost
    drop_penalty: int  # cost of not visiting this stop at all (disjunction penalty)


@dataclass
class VehicleSpec:
    id: str  # the Vehicle's UUID, as a string
    driver_id: str  # the Driver's UUID, as a string
    capacity_weight_grams: int
    capacity_volume_ml: int
    working_hours: TimeWindow
    break_window: TimeWindow | None  # None if the driver has no configured break
    max_working_minutes: int


@dataclass
class RoutingProblem:
    stops: list[Stop]
    vehicles: list[VehicleSpec]
    depot_latitude: float
    depot_longitude: float
    return_to_depot: bool = True


# Soft-time-window lateness penalty and hard-drop penalty, scaled by business
# priority. Units are arbitrary but must satisfy: (a) within a tier, drop >>
# late (never drop a stop just to avoid a small lateness penalty), and (b)
# ordering across tiers is preserved (a VIP lateness penalty must exceed a
# LOW drop penalty is NOT required — drop is always worse than late, even
# for LOW priority — but VIP stops should be dropped only as an absolute
# last resort relative to other tiers).
LATE_PENALTY_BY_PRIORITY = {"low": 100, "normal": 500, "high": 2000, "vip": 10000}
DROP_PENALTY_BY_PRIORITY = {"low": 1_000_000, "normal": 2_000_000, "high": 5_000_000, "vip": 10_000_000}
