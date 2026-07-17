"""Unit tests for app.services.importers.mapping — no DB/HTTP involved."""

from datetime import time

import pytest

from app.schemas.delivery import DeliveryPriority
from app.services.importers.mapping import (
    normalize_row,
    parse_delivery_window,
    parse_unloading_minutes,
)


def test_normalize_row_maps_business_example_headers() -> None:
    raw_row = {
        "Customer Name": "John Smith",
        "Phone": "+380501112233",
        "Address": "Kyiv, Khreshchatyk 10",
        "Order Number": "ORD-42",
        "Priority": "HIGH",
        "Estimated unloading time": "15 minutes",
        "Delivery window": "10:00-12:00",
        "Notes": "Please call before delivery. Gate code 3456. Only after 16:00.",
    }

    result = normalize_row(raw_row)

    assert result.customer_name == "John Smith"
    assert result.phone == "+380501112233"
    assert result.address == "Kyiv, Khreshchatyk 10"
    assert result.order_number == "ORD-42"
    assert result.priority == DeliveryPriority.HIGH
    assert result.unloading_minutes == 15
    assert result.delivery_window_start == time(10, 0)
    assert result.delivery_window_end == time(12, 0)
    assert result.notes == "Please call before delivery. Gate code 3456. Only after 16:00."


def test_normalize_row_raises_when_address_missing() -> None:
    raw_row = {"Customer Name": "John Smith"}

    with pytest.raises(ValueError):
        normalize_row(raw_row)


def test_normalize_row_raises_when_customer_name_missing() -> None:
    raw_row = {"Address": "Kyiv, Khreshchatyk 10"}

    with pytest.raises(ValueError):
        normalize_row(raw_row)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15 minutes", 15),
        ("10", 10),
        ("10 min", 10),
        ("25m", 25),
        (None, 0),
        ("", 0),
    ],
)
def test_parse_unloading_minutes(raw, expected) -> None:
    assert parse_unloading_minutes(raw) == expected


def test_parse_delivery_window_valid() -> None:
    start, end = parse_delivery_window("10:00-12:00")
    assert start == time(10, 0)
    assert end == time(12, 0)


def test_parse_delivery_window_none() -> None:
    assert parse_delivery_window(None) == (None, None)


def test_parse_delivery_window_empty_string() -> None:
    assert parse_delivery_window("") == (None, None)


def test_parse_delivery_window_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        parse_delivery_window("not a window")
