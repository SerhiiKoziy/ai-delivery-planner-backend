"""Google Maps Geocoding API client."""

import httpx

from app.core.config import get_settings

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


class GoogleGeocodingClient:
    """Thin wrapper around the Google Maps Geocoding API."""

    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or get_settings().GOOGLE_MAPS_API_KEY
        self._http_client = http_client

    async def geocode(self, address: str) -> tuple[float, float] | None:
        """Resolve a free-text address to (latitude, longitude).

        Returns None if no API key is configured, on any HTTP error, or
        if the API responds with a non-OK status — geocoding failures are
        expected/recoverable, not exceptional.
        """
        if not self.api_key:
            return None

        params = {"address": address, "key": self.api_key}

        try:
            if self._http_client is not None:
                response = await self._http_client.get(GEOCODE_URL, params=params, timeout=10)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(GEOCODE_URL, params=params)
        except httpx.HTTPError:
            return None

        if response.status_code < 200 or response.status_code >= 300:
            return None

        data = response.json()
        if data.get("status") != "OK":
            return None

        try:
            location = data["results"][0]["geometry"]["location"]
            return float(location["lat"]), float(location["lng"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
