"""Route persistence access."""

from app.db.models.route import Route
from app.repositories.base import BaseRepository


class RouteRepository(BaseRepository[Route]):
    """Repository for Route records."""
