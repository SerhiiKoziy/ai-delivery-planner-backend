"""Organization persistence access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """Repository for Organization records — the tenant root, so unscoped."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Organization)
