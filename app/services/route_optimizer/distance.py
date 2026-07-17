"""Straight-line (haversine) distance/duration estimation.

MVP simplification: real turn-by-road distance and live traffic would come
from the Google Distance Matrix API. This module estimates both from
great-circle distance and an assumed average urban delivery speed, which is
enough to exercise the OR-Tools solver end-to-end without an extra paid API
dependency. Swapping in a real Distance Matrix provider later only requires
replacing `build_distance_duration_matrix`'s implementation — callers
(builder.py) don't need to change.
"""

import math

EARTH_RADIUS_KM = 6371.0
AVERAGE_SPEED_KMH = 30.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def build_distance_duration_matrix(
    coordinates: list[tuple[float, float]],
) -> tuple[list[list[int]], list[list[int]]]:
    """Build (distance_meters, duration_minutes) matrices for the given coordinates.

    `coordinates[0]` must be the depot; the rest are stops in RoutingProblem.stops
    order. Both matrices are square, symmetric, and integer-valued (required by
    OR-Tools transit callbacks).
    """
    n = len(coordinates)
    distance_matrix = [[0] * n for _ in range(n)]
    duration_matrix = [[0] * n for _ in range(n)]

    for i in range(n):
        lat1, lng1 = coordinates[i]
        for j in range(i + 1, n):
            lat2, lng2 = coordinates[j]
            km = haversine_km(lat1, lng1, lat2, lng2)
            meters = round(km * 1000)
            minutes = max(0, round(km / AVERAGE_SPEED_KMH * 60))
            distance_matrix[i][j] = meters
            distance_matrix[j][i] = meters
            duration_matrix[i][j] = minutes
            duration_matrix[j][i] = minutes

    return distance_matrix, duration_matrix
