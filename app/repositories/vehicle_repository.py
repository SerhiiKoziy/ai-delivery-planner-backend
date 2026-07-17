"""Vehicle persistence access."""

from app.db.models.vehicle import Vehicle
from app.repositories.base import BaseRepository


class VehicleRepository(BaseRepository[Vehicle]):
    """Repository for Vehicle records."""
