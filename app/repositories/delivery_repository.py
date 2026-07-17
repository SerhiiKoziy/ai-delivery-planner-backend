"""Delivery persistence access."""

from app.db.models.delivery import Delivery
from app.repositories.base import BaseRepository


class DeliveryRepository(BaseRepository[Delivery]):
    """Repository for Delivery records."""
