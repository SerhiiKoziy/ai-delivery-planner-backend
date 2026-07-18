"""Parses free-text delivery notes into structured JSON via the LLM."""

import json

from openai import AsyncOpenAI

from app.schemas.ai import ParsedDeliveryNote
from app.services.ai.client import create_structured_completion

_SYSTEM_PROMPT = (
    "You are an assistant that extracts structured delivery-instruction data from "
    "free-text courier notes. Notes may be in Ukrainian, Russian, or English. For "
    "each note, extract: whether the customer must be called before delivery "
    "(call_before) and how many minutes in advance if stated, else null "
    "(call_before_minutes); a gate/entry code if one is mentioned, else null "
    "(gate_code); the earliest acceptable delivery time as 24-hour HH:MM if a "
    "constraint like 'only after 16:00' is mentioned, else null (earliest_time); "
    "whether a dog/pet on the property is mentioned (has_dog); and any other "
    "actionable instructions not already captured above, as short strings "
    "(other_instructions, empty list if none). Return one result per input note, "
    "preserving its `index` field exactly so results can be matched back to inputs."
)

_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "call_before": {"type": "boolean"},
                    "call_before_minutes": {"type": ["integer", "null"]},
                    "gate_code": {"type": ["string", "null"]},
                    "earliest_time": {"type": ["string", "null"]},
                    "has_dog": {"type": "boolean"},
                    "other_instructions": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "index",
                    "call_before",
                    "call_before_minutes",
                    "gate_code",
                    "earliest_time",
                    "has_dog",
                    "other_instructions",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["notes"],
    "additionalProperties": False,
}


async def parse_delivery_notes(
    raw_texts: list[str | None],
    *,
    client: AsyncOpenAI,
    model: str,
) -> list[ParsedDeliveryNote | None]:
    """Extract structured fields from a batch of free-text delivery notes.

    Sends every non-empty text in a single OpenAI call, aligned back to the
    input list by index. Empty/None entries map to `None` without being sent
    to the model at all (no wasted calls on blank notes).
    """
    indexed_texts = [(i, text) for i, text in enumerate(raw_texts) if text and text.strip()]

    results: list[ParsedDeliveryNote | None] = [None] * len(raw_texts)
    if not indexed_texts:
        return results

    payload = [{"index": i, "text": text} for i, text in indexed_texts]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"notes": payload}, ensure_ascii=False)},
    ]

    data = await create_structured_completion(
        client,
        model=model,
        messages=messages,
        schema_name="parsed_delivery_notes",
        json_schema=_NOTES_SCHEMA,
    )

    for item in data.get("notes", []):
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(raw_texts)):
            continue
        results[index] = ParsedDeliveryNote(
            call_before=item.get("call_before", False),
            call_before_minutes=item.get("call_before_minutes"),
            gate_code=item.get("gate_code"),
            earliest_time=item.get("earliest_time"),
            has_dog=item.get("has_dog", False),
            other_instructions=item.get("other_instructions", []),
        )
    return results


async def parse_delivery_note(
    raw_text: str,
    *,
    client: AsyncOpenAI,
    model: str,
) -> ParsedDeliveryNote | None:
    """Extract structured fields (e.g. access instructions, preferred time) from free text.

    Thin wrapper around `parse_delivery_notes` for a single input; prefer the
    batched function when processing multiple rows.
    """
    results = await parse_delivery_notes([raw_text], client=client, model=model)
    return results[0]
