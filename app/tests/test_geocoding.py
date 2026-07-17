"""Tests for the Google Geocoding client, with all HTTP calls mocked out."""

import httpx
import pytest

from app.services.geocoding.client import GoogleGeocodingClient


@pytest.mark.asyncio
async def test_geocode_returns_none_without_api_key() -> None:
    client = GoogleGeocodingClient(api_key="")
    result = await client.geocode("Kyiv, Khreshchatyk 10")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_returns_coordinates_on_ok_status() -> None:
    canned_response = {
        "status": "OK",
        "results": [
            {"geometry": {"location": {"lat": 50.4501, "lng": 30.5234}}},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=canned_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GoogleGeocodingClient(api_key="fake-key", http_client=http_client)
        result = await client.geocode("Kyiv, Khreshchatyk 10")

    assert result == (50.4501, 30.5234)


@pytest.mark.asyncio
async def test_geocode_returns_none_on_zero_results() -> None:
    canned_response = {"status": "ZERO_RESULTS", "results": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=canned_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GoogleGeocodingClient(api_key="fake-key", http_client=http_client)
        result = await client.geocode("Nowhere")

    assert result is None
