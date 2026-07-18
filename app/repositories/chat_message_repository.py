"""ChatMessage persistence access."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat_message import ChatMessage
from app.repositories.base import BaseRepository


class ChatMessageRepository(BaseRepository[ChatMessage]):
    """Repository for ChatMessage records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ChatMessage)

    async def list_by_route(self, route_id: uuid.UUID) -> list[ChatMessage]:
        """Fetch all chat messages for a route, oldest first."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.route_id == route_id)
            .order_by(ChatMessage.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
