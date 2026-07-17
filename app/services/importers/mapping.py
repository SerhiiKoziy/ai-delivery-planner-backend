"""Normalization of raw imported rows (arbitrary header casing/spacing)
into the canonical DeliveryImportRow shape.
"""

import re
from datetime import time

from app.schemas.delivery import DeliveryImportRow, DeliveryPriority

# Canonical field -> accepted header aliases (compared case-insensitively,
# with spaces/underscores/hyphens stripped).
_FIELD_ALIASES: dict[str, list[str]] = {
    "customer_name": ["Customer Name", "Customer", "Name"],
    "phone": ["Phone", "Phone Number"],
    "address": ["Address"],
    "order_number": ["Order Number", "Order #", "Order"],
    "priority": ["Priority"],
    "unloading_minutes": ["Estimated unloading time", "Unloading Time", "Unloading"],
    "delivery_window": ["Delivery window", "Delivery Window", "Time Window"],
    "notes": ["Notes", "Note", "Comment", "Comments"],
}


def _normalize_key(key: str) -> str:
    """Lower-case and strip spaces/underscores/hyphens for alias matching."""
    return re.sub(r"[\s_\-]+", "", key.strip().lower())


# Build a reverse lookup: normalized alias -> canonical field name.
_ALIAS_LOOKUP: dict[str, str] = {
    _normalize_key(alias): field
    for field, aliases in _FIELD_ALIASES.items()
    for alias in aliases
}


def parse_unloading_minutes(raw) -> int:
    """Parse a free-text/number unloading-time value into whole minutes.

    Accepts an int/float already, or a string like "15 minutes", "15",
    "10 min", "25m". Returns 0 if raw is empty/None/unparseable.
    """
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return 0
    match = re.search(r"\d+", text)
    if not match:
        return 0
    return int(match.group())


def _parse_time_of_day(text: str) -> time:
    text = text.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        raise ValueError(f"Invalid time value: {text!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    return time(hour=hour, minute=minute)


def parse_delivery_window(raw) -> tuple[time | None, time | None]:
    """Parse a delivery window string like "10:00-12:00" into (start, end).

    Returns (None, None) if raw is empty/None. Raises ValueError on a
    malformed non-empty string.
    """
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None

    normalized = text.replace("–", "-").replace("—", "-")
    parts = normalized.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid delivery window: {text!r}")

    start_text, end_text = parts[0].strip(), parts[1].strip()
    if not start_text or not end_text:
        raise ValueError(f"Invalid delivery window: {text!r}")

    start = _parse_time_of_day(start_text)
    end = _parse_time_of_day(end_text)
    return start, end


def _parse_priority(raw) -> DeliveryPriority:
    if raw is None:
        return DeliveryPriority.NORMAL
    text = str(raw).strip().lower()
    if not text:
        return DeliveryPriority.NORMAL
    try:
        return DeliveryPriority(text)
    except ValueError:
        return DeliveryPriority.NORMAL


def normalize_row(raw_row: dict) -> DeliveryImportRow:
    """Map an arbitrary-cased/spaced raw row dict into a DeliveryImportRow.

    Raises ValueError if the mandatory `address` or `customer_name` fields
    can't be located among the row's headers.
    """
    fields: dict[str, object] = {}
    for raw_key, value in raw_row.items():
        if raw_key is None:
            continue
        canonical = _ALIAS_LOOKUP.get(_normalize_key(str(raw_key)))
        if canonical is not None:
            fields[canonical] = value

    customer_name = fields.get("customer_name")
    address = fields.get("address")

    customer_name = str(customer_name).strip() if customer_name is not None else ""
    address = str(address).strip() if address is not None else ""

    if not address:
        raise ValueError("Missing required field: address")
    if not customer_name:
        raise ValueError("Missing required field: customer_name")

    phone = fields.get("phone")
    phone = str(phone).strip() or None if phone is not None else None

    order_number = fields.get("order_number")
    order_number = str(order_number).strip() or None if order_number is not None else None

    notes = fields.get("notes")
    notes = str(notes).strip() or None if notes is not None else None

    priority = _parse_priority(fields.get("priority"))
    unloading_minutes = parse_unloading_minutes(fields.get("unloading_minutes"))
    window_start, window_end = parse_delivery_window(fields.get("delivery_window"))

    return DeliveryImportRow(
        customer_name=customer_name,
        phone=phone,
        address=address,
        order_number=order_number,
        priority=priority,
        unloading_minutes=unloading_minutes,
        delivery_window_start=window_start,
        delivery_window_end=window_end,
        notes=notes,
    )
