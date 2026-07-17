"""Analyzes an imported delivery list: address cleanup and duplicate detection.

Does not optimize routes — see services.route_optimizer for that.
"""


async def analyze_delivery_list(rows: list) -> dict:
    """Clean addresses and flag likely duplicates in a freshly imported delivery list."""
    raise NotImplementedError
