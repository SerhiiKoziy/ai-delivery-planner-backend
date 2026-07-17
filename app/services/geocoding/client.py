"""Google Maps Geocoding API client."""

from app.core.config import get_settings


class GoogleGeocodingClient:
    """Thin wrapper around the Google Maps Geocoding API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().GOOGLE_MAPS_API_KEY

    async def geocode(self, address: str) -> tuple[float, float]:
        """Resolve a free-text address to (latitude, longitude)."""
        raise NotImplementedError
