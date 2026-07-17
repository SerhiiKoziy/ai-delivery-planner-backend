"""Route optimization service, wrapping Google OR-Tools.

The LLM is never used for route optimization — this package owns that
responsibility exclusively, respecting time windows, priorities, vehicle
capacity, and driver working hours.
"""
