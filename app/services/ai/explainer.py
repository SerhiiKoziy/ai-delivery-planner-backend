"""Explains OR-Tools route decisions in natural language."""

from openai import AsyncOpenAI

from app.schemas.delivery import DeliveryRead
from app.schemas.route import RouteRead

_SYSTEM_PROMPT = (
    "You are a logistics assistant explaining why a delivery route was sequenced "
    "the way it was. You are given an ordered list of stops with their estimated "
    "arrival/departure times, distance from the previous stop, and each stop's "
    "customer name, priority tier, and delivery time window. Write a short, clear "
    "explanation (2-5 sentences) of the sequencing for a dispatcher: call out "
    "stops that ended up early or late in the route and why — driven by delivery "
    "time windows, customer priority, or proximity/distance. Only use facts given "
    "in the route summary; do not invent details."
)


def build_route_summary(route: RouteRead, deliveries: list[DeliveryRead]) -> str:
    """Build a compact textual summary of a route's stops for LLM context.

    Shared by explainer.py and chat.py so both features describe the route
    identically to the model.
    """
    deliveries_by_id = {d.id: d for d in deliveries}
    lines = [
        f"Route {route.id} (status={route.status}, "
        f"total_distance_km={route.total_distance_km:.1f}, "
        f"total_duration_minutes={route.total_duration_minutes}, "
        f"return_to_depot={route.return_to_depot}):"
    ]
    for stop in sorted(route.stops, key=lambda s: s.sequence):
        delivery = deliveries_by_id.get(stop.delivery_id)
        customer = delivery.customer_name if delivery else "unknown customer"
        priority = delivery.priority.value if delivery else "unknown"
        if delivery and (delivery.delivery_window_start or delivery.delivery_window_end):
            window = f"{delivery.delivery_window_start}-{delivery.delivery_window_end}"
        else:
            window = "no window"
        address = delivery.address if delivery else "unknown address"
        lines.append(
            f"  Stop {stop.sequence}: {customer} ({address}) | priority={priority} | "
            f"window={window} | arrival={stop.estimated_arrival} | "
            f"departure={stop.estimated_departure} | "
            f"distance_from_previous_km={stop.distance_from_previous_km:.2f}"
        )
    return "\n".join(lines)


async def explain_route(
    route: RouteRead,
    deliveries: list[DeliveryRead],
    *,
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Generate a human-readable explanation of why a route was sequenced this way."""
    summary = build_route_summary(route, deliveries)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": summary},
    ]
    response = await client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content or ""
