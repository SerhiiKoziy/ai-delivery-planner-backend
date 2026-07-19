"""Organization persistence access."""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """Repository for Organization records — the tenant root, so unscoped."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Organization)

    async def increment_route_count(self, organization_id: uuid.UUID, by: int) -> Organization:
        """Atomically add `by` to `routes_generated_count` and return the updated row.

        Issued as a single `SET x = x + :by` statement (not read-modify-write)
        so concurrent route-generation requests for the same organization
        can't lose an increment to a race.
        """
        stmt = (
            update(Organization)
            .where(Organization.id == organization_id)
            .values(routes_generated_count=Organization.routes_generated_count + by)
            .returning(Organization)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()

    async def try_consume_quota(
        self,
        organization_id: uuid.UUID,
        *,
        counter_column: str,
        limit: int | None,
        amount: int = 1,
    ) -> bool:
        """Atomically add `amount` to `counter_column`, but only if doing so
        would not exceed `limit` (`None` = unlimited, always succeeds).

        A single conditional `UPDATE ... WHERE column + amount <= limit`, not
        a separate check-then-write, so concurrent requests against the same
        organization can't race past the cap. Returns whether the increment
        was applied.
        """
        column = getattr(Organization, counter_column)
        stmt = update(Organization).where(Organization.id == organization_id)
        if limit is not None:
            stmt = stmt.where(column + amount <= limit)
        stmt = stmt.values(**{counter_column: column + amount})
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
