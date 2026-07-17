"""Driver persistence access."""

from app.db.models.driver import Driver
from app.repositories.base import BaseRepository


class DriverRepository(BaseRepository[Driver]):
    """Repository for Driver records."""
