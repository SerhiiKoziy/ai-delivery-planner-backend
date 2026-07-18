"""Interprets free-text dispatcher messages into a structured replan action,
and explains the resulting before/after diff in natural language.

The LLM never invents or echoes UUIDs: it references the affected delivery
by `affected_stop_sequence` (a small integer already visible to it in the
pending-stops context), and the caller deterministically resolves
sequence -> delivery_id by looking it up among the route's pending stops.
"""

import json
import uuid
from datetime import time

from openai import AsyncOpenAI

from app.db.models.route_stop import RouteStop
from app.schemas.ai import ReplanEventType, ReplanInterpretation, StopDiffEntry
from app.schemas.route import RouteStopRead
from app.services.ai.client import create_structured_completion

_STOP_REQUIRED_EVENT_TYPES = {
    ReplanEventType.CUSTOMER_UNREACHABLE,
    ReplanEventType.DELIVERY_CANCELLED,
    ReplanEventType.DELIVERY_RESCHEDULED,
}

_INTERPRET_SYSTEM_PROMPT = (
    "You are a dispatch assistant that interprets a free-text message from a "
    "delivery dispatcher (in Ukrainian, Russian, or English) and classifies it "
    "into one of these event types:\n"
    "- customer_unreachable: the customer/recipient cannot be reached (e.g. "
    "not answering the phone/door). Requires affected_stop_sequence.\n"
    "- delivery_cancelled: the delivery itself was cancelled by the customer "
    "or dispatcher. Requires affected_stop_sequence.\n"
    "- delivery_rescheduled: the customer asked for a different delivery time "
    "window. Requires affected_stop_sequence, new_window_start, and "
    "new_window_end, each as 24-hour \"HH:MM\" strings.\n"
    "- driver_delayed: the driver is delayed for the whole route (e.g. stuck "
    "in traffic, vehicle issue), not tied to one specific stop. Requires "
    "delay_minutes (a positive integer estimate).\n"
    "- unrecognized: the message doesn't clearly match any of the above, or "
    "doesn't identify which stop it concerns when one of the above requires it.\n"
    "You are given the list of currently pending stops on the route (each with "
    "its `sequence` integer, customer_name, address, delivery window, and "
    "priority) and the dispatcher's raw message. Identify the affected stop by "
    "matching a client number, customer name, or address mentioned in the "
    "message to the correct `sequence` value from the pending-stops list — "
    "NEVER invent a sequence number that isn't in that list. Always fill in "
    "`summary` with a short one-sentence description of what you understood "
    "from the message. Leave fields that don't apply to the chosen event_type "
    "as null."
)

_INTERPRETATION_SCHEMA = {
    "type": "object",
    "properties": {
        "event_type": {
            "type": "string",
            "enum": [event_type.value for event_type in ReplanEventType],
        },
        "affected_stop_sequence": {"type": ["integer", "null"]},
        "new_window_start": {"type": ["string", "null"]},
        "new_window_end": {"type": ["string", "null"]},
        "delay_minutes": {"type": ["integer", "null"]},
        "summary": {"type": "string"},
    },
    "required": [
        "event_type",
        "affected_stop_sequence",
        "new_window_start",
        "new_window_end",
        "delay_minutes",
        "summary",
    ],
    "additionalProperties": False,
}

_EXPLAIN_SYSTEM_PROMPT = (
    "You are a logistics dispatch assistant summarizing the result of an "
    "automatic route replan that was triggered by a dispatcher's message. You "
    "are given: what the system understood happened (interpretation summary), "
    "the list of stops that actually changed (with old/new sequence and "
    "arrival time), and the route's total distance/duration before and after. "
    "Write a short (2-4 sentence) plain-language explanation of what changed "
    "and why, mentioning time saved or lost. Only use the facts given; do not "
    "invent details. Example style: 'Client at stop 5 was unreachable, so it "
    "was moved to the end of the route. Total time saved: 12 minutes.'"
)


async def interpret_replan_message(
    message: str,
    pending_stops: list[dict],
    *,
    client: AsyncOpenAI,
    model: str,
) -> ReplanInterpretation:
    """Classify a dispatcher's free-text message into a `ReplanInterpretation`.

    `pending_stops` items look like `{"sequence": int, "customer_name": str,
    "address": str, "delivery_window_start": str | None,
    "delivery_window_end": str | None, "priority": str}` — built from the
    route's currently-pending stops only.

    Defensively downgrades `event_type` to `unrecognized` (in Python, not just
    trusting the model) whenever an event type that needs an affected stop
    comes back with a missing or out-of-range `affected_stop_sequence` — this
    is expected/normal for ambiguous dispatcher input, not an error.
    """
    messages = [
        {"role": "system", "content": _INTERPRET_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"pending_stops": pending_stops, "message": message}, ensure_ascii=False
            ),
        },
    ]

    data = await create_structured_completion(
        client,
        model=model,
        messages=messages,
        schema_name="replan_interpretation",
        json_schema=_INTERPRETATION_SCHEMA,
    )

    interpretation = ReplanInterpretation(
        event_type=data.get("event_type", ReplanEventType.UNRECOGNIZED.value),
        affected_stop_sequence=data.get("affected_stop_sequence"),
        new_window_start=data.get("new_window_start"),
        new_window_end=data.get("new_window_end"),
        delay_minutes=data.get("delay_minutes"),
        summary=data.get("summary", ""),
    )

    known_sequences = {stop["sequence"] for stop in pending_stops}
    if interpretation.event_type in _STOP_REQUIRED_EVENT_TYPES and (
        interpretation.affected_stop_sequence is None
        or interpretation.affected_stop_sequence not in known_sequences
    ):
        interpretation = interpretation.model_copy(
            update={
                "event_type": ReplanEventType.UNRECOGNIZED,
                "summary": (
                    "Could not identify which pending delivery/stop this message "
                    "refers to; the dispatcher should clarify with a specific stop "
                    "or client reference."
                ),
            }
        )

    return interpretation


async def explain_replan(
    interpretation: ReplanInterpretation,
    diff: list[StopDiffEntry],
    distance_before: float,
    distance_after: float,
    duration_before: int,
    duration_after: int,
    *,
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Generate a short natural-language explanation of a replan's effect."""
    lines = [f"What happened: {interpretation.summary}"]
    if diff:
        lines.append("Stops that changed:")
        for entry in diff:
            lines.append(
                f"  - {entry.customer_name}: {entry.change} "
                f"(sequence {entry.old_sequence} -> {entry.new_sequence}, "
                f"arrival {entry.old_estimated_arrival} -> {entry.new_estimated_arrival})"
                + (f" [{entry.reason}]" if entry.reason else "")
            )
    else:
        lines.append("No stops changed.")
    lines.append(
        f"Totals before: distance={distance_before:.1f} km, duration={duration_before} min"
    )
    lines.append(
        f"Totals after: distance={distance_after:.1f} km, duration={duration_after} min"
    )

    messages = [
        {"role": "system", "content": _EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
    response = await client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content or ""


def parse_hhmm(value: str | None) -> time | None:
    """Parse a "HH:MM" string into a `time`, returning None if malformed/absent.

    Used defensively on LLM-produced window strings so bad model output
    downgrades the interpretation instead of crashing the request.
    """
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return time(hour, minute)


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def build_stop_diff(
    stops_before: list[RouteStop],
    stops_after: list[RouteStopRead],
    customer_names: dict[uuid.UUID, str],
    event_type: ReplanEventType,
    *,
    rescheduled_delivery_id: uuid.UUID | None = None,
    new_window_start: str | None = None,
    new_window_end: str | None = None,
) -> list[StopDiffEntry]:
    """Diff a route's pre-replan stops (ORM) against its post-replan stops.

    - A before-stop missing from `stops_after` -> "removed" (excluded/cancelled).
    - A before-stop that was already completed/skipped (not "pending") and is
      still present -> "unchanged" (replan() never touches non-pending stops).
    - Among pending-vs-pending stops: sequence changed -> "reordered"; arrival
      time shifted by more than a minute -> "time_shifted"; the just-rescheduled
      delivery with neither of the above -> "window_updated"; else "unchanged".
    """
    stops_after_by_delivery = {stop.delivery_id: stop for stop in stops_after}
    entries: list[StopDiffEntry] = []

    for before in stops_before:
        customer_name = customer_names.get(before.delivery_id, "unknown customer")
        after = stops_after_by_delivery.get(before.delivery_id)

        if after is None:
            entries.append(
                StopDiffEntry(
                    delivery_id=before.delivery_id,
                    customer_name=customer_name,
                    change="removed",
                    old_sequence=before.sequence,
                    new_sequence=None,
                    old_estimated_arrival=before.estimated_arrival,
                    new_estimated_arrival=None,
                    reason=f"Marked {event_type.value} by dispatcher",
                )
            )
            continue

        reason: str | None = None
        if before.status != "pending":
            change = "unchanged"
        elif before.sequence != after.sequence:
            change = "reordered"
        elif (
            abs(_time_to_minutes(before.estimated_arrival) - _time_to_minutes(after.estimated_arrival))
            > 1
        ):
            change = "time_shifted"
        elif rescheduled_delivery_id is not None and before.delivery_id == rescheduled_delivery_id:
            change = "window_updated"
            reason = f"Delivery window changed to {new_window_start}-{new_window_end} per dispatcher request"
        else:
            change = "unchanged"

        entries.append(
            StopDiffEntry(
                delivery_id=before.delivery_id,
                customer_name=customer_name,
                change=change,
                old_sequence=before.sequence,
                new_sequence=after.sequence,
                old_estimated_arrival=before.estimated_arrival,
                new_estimated_arrival=after.estimated_arrival,
                reason=reason,
            )
        )

    return entries
