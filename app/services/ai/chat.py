"""Conversational Q&A over route/delivery data, including mid-route replanning suggestions."""

from openai import AsyncOpenAI

from app.schemas.delivery import DeliveryRead
from app.schemas.route import RouteRead
from app.services.ai.explainer import build_route_summary

_SYSTEM_PROMPT = (
    "You are a helpful dispatch assistant answering questions about a specific "
    "delivery route. Use only the route summary given as context to answer. Be "
    "concise. When useful, suggest concrete replanning actions (e.g. reordering "
    "stops, calling a customer, flagging a delay) but make clear you are only "
    "suggesting — you cannot execute changes yourself."
)


async def handle_chat_message(
    message: str,
    route: RouteRead,
    deliveries: list[DeliveryRead],
    *,
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Answer a user question about a route/its deliveries, or suggest a replan."""
    summary = build_route_summary(route, deliveries)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "system", "content": f"Route context:\n{summary}"},
        {"role": "user", "content": message},
    ]
    response = await client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content or ""
