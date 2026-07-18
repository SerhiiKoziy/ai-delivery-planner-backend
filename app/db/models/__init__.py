"""SQLAlchemy models package. Import all models here so Base.metadata is complete
for Alembic autogeneration.
"""

from app.db.models.base import Base
from app.db.models.chat_message import ChatMessage
from app.db.models.delivery import Delivery
from app.db.models.delivery_note import DeliveryNote
from app.db.models.depot import Depot
from app.db.models.driver import Driver
from app.db.models.organization import Organization
from app.db.models.route import Route
from app.db.models.route_stop import RouteStop
from app.db.models.user import User
from app.db.models.vehicle import Vehicle

__all__ = [
    "Base",
    "ChatMessage",
    "Delivery",
    "DeliveryNote",
    "Depot",
    "Driver",
    "Organization",
    "Route",
    "RouteStop",
    "User",
    "Vehicle",
]
