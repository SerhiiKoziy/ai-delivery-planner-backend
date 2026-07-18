"""Analyzes an imported delivery list: address cleanup and duplicate detection.

Does not optimize routes — see services.route_optimizer for that. Runs before
geocoding/import commit: this is a preview step, not a persistence step.
"""

import json

from openai import AsyncOpenAI

from app.schemas.ai import (
    AddressCleaningResult,
    DeliveryAnalysisResult,
    DeliveryRowAnalysis,
    DuplicateGroup,
)
from app.schemas.delivery import DeliveryImportRow
from app.services.ai.client import create_structured_completion
from app.services.ai.parser import parse_delivery_notes

_ADDRESS_SYSTEM_PROMPT = (
    "You clean and normalize delivery addresses, mostly Ukrainian, occasionally "
    "transliterated to English. For each address: fix typos, expand abbreviated "
    "street/city names, and infer a city and postal code only when confidently "
    "derivable from the address text itself (otherwise leave them null). Produce "
    "a normalized full-address string. Report a confidence score between 0 and 1 "
    "for the normalization, and a list of short human-readable descriptions of "
    "what was corrected (empty list if nothing needed correcting). Return one "
    "result per input address, preserving its `index` field exactly."
)

_ADDRESS_SCHEMA = {
    "type": "object",
    "properties": {
        "addresses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "normalized": {"type": "string"},
                    "city": {"type": ["string", "null"]},
                    "postal_code": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "corrections": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "index",
                    "normalized",
                    "city",
                    "postal_code",
                    "confidence",
                    "corrections",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["addresses"],
    "additionalProperties": False,
}

_DUPLICATE_SYSTEM_PROMPT = (
    "You detect likely duplicate customers/orders in an imported delivery list. "
    "Rows may refer to the same real-world customer despite differing formatting "
    "(e.g. legal-entity quoting styles, transliteration, abbreviations, minor "
    "typos). Group only rows that are likely the same customer/order; every "
    "group must contain 2 or more row_numbers taken from the input. Rows with no "
    "likely duplicate must not appear in any group."
)

_DUPLICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_indices": {"type": "array", "items": {"type": "integer"}},
                    "customer_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["row_indices", "customer_name", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}


async def _clean_addresses(
    rows: list[DeliveryImportRow],
    *,
    client: AsyncOpenAI,
    model: str,
) -> list[AddressCleaningResult]:
    """Clean/normalize every row's address in a single OpenAI call."""
    if not rows:
        return []

    payload = [{"index": i, "address": row.address} for i, row in enumerate(rows)]
    messages = [
        {"role": "system", "content": _ADDRESS_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"addresses": payload}, ensure_ascii=False)},
    ]

    data = await create_structured_completion(
        client,
        model=model,
        messages=messages,
        schema_name="cleaned_addresses",
        json_schema=_ADDRESS_SCHEMA,
    )

    results: list[AddressCleaningResult | None] = [None] * len(rows)
    for item in data.get("addresses", []):
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(rows)):
            continue
        results[index] = AddressCleaningResult(
            original=rows[index].address,
            normalized=item.get("normalized") or rows[index].address,
            city=item.get("city"),
            postal_code=item.get("postal_code"),
            confidence=item.get("confidence", 0.0),
            corrections=item.get("corrections", []),
        )

    # Defensive fallback in case the model omits an index for some row.
    for i, row in enumerate(rows):
        if results[i] is None:
            results[i] = AddressCleaningResult(
                original=row.address, normalized=row.address, confidence=0.0
            )
    return results  # type: ignore[return-value]


async def _detect_duplicates(
    rows: list[DeliveryImportRow],
    *,
    client: AsyncOpenAI,
    model: str,
) -> list[DuplicateGroup]:
    """Flag groups of rows that likely refer to the same customer/order, in one call."""
    if len(rows) < 2:
        return []

    payload = [
        {"row_number": i + 1, "customer_name": row.customer_name, "address": row.address}
        for i, row in enumerate(rows)
    ]
    messages = [
        {"role": "system", "content": _DUPLICATE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"rows": payload}, ensure_ascii=False)},
    ]

    data = await create_structured_completion(
        client,
        model=model,
        messages=messages,
        schema_name="duplicate_groups",
        json_schema=_DUPLICATE_SCHEMA,
    )

    groups: list[DuplicateGroup] = []
    for item in data.get("groups", []):
        row_indices = [i for i in item.get("row_indices", []) if isinstance(i, int)]
        if len(row_indices) < 2:
            continue
        groups.append(
            DuplicateGroup(
                row_indices=row_indices,
                customer_name=item.get("customer_name", ""),
                reason=item.get("reason", ""),
            )
        )
    return groups


async def analyze_delivery_list(
    rows: list[DeliveryImportRow],
    *,
    client: AsyncOpenAI,
    model: str,
) -> DeliveryAnalysisResult:
    """Clean addresses, parse notes, and flag likely duplicates in a freshly imported list.

    Makes exactly one OpenAI call for address cleaning, one for note parsing
    (skipped entirely if every note is empty), and one for duplicate detection
    (skipped if there are fewer than 2 rows) — never one call per row.
    """
    addresses = await _clean_addresses(rows, client=client, model=model)
    parsed_notes = await parse_delivery_notes(
        [row.notes for row in rows], client=client, model=model
    )
    duplicate_groups = await _detect_duplicates(rows, client=client, model=model)

    row_analyses = [
        DeliveryRowAnalysis(
            row_number=i + 1,
            address=addresses[i],
            parsed_note=parsed_notes[i],
        )
        for i in range(len(rows))
    ]

    return DeliveryAnalysisResult(
        total_rows=len(rows),
        rows=row_analyses,
        duplicate_groups=duplicate_groups,
    )
