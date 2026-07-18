"""Integration tests for POST /api/v1/ai/analyze.

Uses the `ai_client` fixture from conftest.py, which layers a fake
AsyncOpenAI-shaped client (never hits the network) on top of the standard
authenticated `client` fixture.
"""

import csv
import io

from fastapi.testclient import TestClient

from app.tests.conftest import FakeOpenAIClient


def _make_csv(rows: list[dict], fieldnames: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def test_analyze_cleans_addresses_parses_notes_and_flags_duplicates(
    ai_client: TestClient, mock_openai_client: FakeOpenAIClient
) -> None:
    fieldnames = ["Customer Name", "Address", "Notes"]
    rows = [
        {
            "Customer Name": "ТОВ Ромашка",
            "Address": "Kyiv Khreshchatyk 1",
            "Notes": (
                "Please call before delivery. Gate code 3456. "
                "Only after 16:00. Dog in yard."
            ),
        },
        {
            "Customer Name": "ТОВ Ромашка",
            "Address": "Kyiv Khreshchatyk 1a",
            "Notes": "",
        },
    ]
    csv_bytes = _make_csv(rows, fieldnames)

    response = ai_client.post(
        "/api/v1/ai/analyze",
        files={"file": ("delivery_list.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["total_rows"] == 2
    assert len(body["rows"]) == 2

    first, second = body["rows"]
    assert first["row_number"] == 1
    assert first["address"]["original"] == "Kyiv Khreshchatyk 1"
    assert first["address"]["normalized"] == "Kyiv Khreshchatyk 1"
    assert first["parsed_note"] is not None
    assert first["parsed_note"]["call_before"] is True
    assert first["parsed_note"]["gate_code"] == "3456"
    assert first["parsed_note"]["earliest_time"] == "16:00"
    assert first["parsed_note"]["has_dog"] is True

    assert second["row_number"] == 2
    assert second["parsed_note"] is None

    assert len(body["duplicate_groups"]) == 1
    assert sorted(body["duplicate_groups"][0]["row_indices"]) == [1, 2]

    # Exactly 3 OpenAI calls: address cleaning, note parsing, duplicate
    # detection — never one call per row.
    assert len(mock_openai_client.calls) == 3


def test_analyze_skips_note_parsing_call_when_all_notes_are_empty(
    ai_client: TestClient, mock_openai_client: FakeOpenAIClient
) -> None:
    fieldnames = ["Customer Name", "Address"]
    rows = [{"Customer Name": "Solo Customer", "Address": "Kyiv Khreshchatyk 5"}]
    csv_bytes = _make_csv(rows, fieldnames)

    response = ai_client.post(
        "/api/v1/ai/analyze",
        files={"file": ("delivery_list.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["parsed_note"] is None
    assert body["duplicate_groups"] == []

    # Only the address-cleaning call: no notes to parse, fewer than 2 rows
    # so duplicate detection is also skipped.
    assert len(mock_openai_client.calls) == 1


def test_analyze_rejects_unsupported_file_extension(ai_client: TestClient) -> None:
    response = ai_client.post(
        "/api/v1/ai/analyze",
        files={"file": ("delivery_list.txt", b"whatever", "text/plain")},
    )
    assert response.status_code == 400
