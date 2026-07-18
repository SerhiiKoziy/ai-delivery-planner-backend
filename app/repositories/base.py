"""Generic base repository providing common async CRUD operations."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """Generic repository over a single SQLAlchemy model."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get(self, id) -> ModelType | None:
        """Fetch a single record by id."""
        return await self.session.get(self.model, id)

    async def get_many(self, ids) -> list[ModelType]:
        """Fetch multiple records by id, in no particular order."""
        stmt = select(self.model).where(self.model.id.in_(ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list(self) -> list[ModelType]:
        """Fetch all records, newest first."""
        stmt = select(self.model).order_by(self.model.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs) -> ModelType:
        """Create and persist a new record."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def update(self, id, **kwargs) -> ModelType | None:
        """Update an existing record by id. Returns None if not found."""
        instance = await self.get(id)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id) -> bool:
        """Delete a record by id. Returns True if a record was deleted."""
        instance = await self.get(id)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.commit()
        return True


class TenantScopedRepository(BaseRepository[ModelType]):
    """A BaseRepository whose model has an `organization_id` column.

    The organization is bound once at construction (from the caller's
    authenticated identity, via DI) rather than passed per-call, so every
    read/write this repository makes is automatically confined to that
    organization — there's no method call site where a caller could forget
    to scope a query. `update`/`delete` need no override beyond `update`'s
    kwargs guard: they call `self.get(id)`, which resolves to this class's
    scoped `get` by ordinary method dispatch.
    """

    def __init__(self, session: AsyncSession, model: type[ModelType], organization_id) -> None:
        super().__init__(session, model)
        self.organization_id = organization_id

    async def get(self, id) -> ModelType | None:
        """Fetch a single record by id, scoped to this repository's organization."""
        stmt = select(self.model).where(
            self.model.id == id, self.model.organization_id == self.organization_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many(self, ids) -> list[ModelType]:
        """Fetch multiple records by id, scoped to this repository's organization.

        Ids belonging to another organization are silently absent from the
        result — indistinguishable from ids that don't exist at all.
        """
        stmt = select(self.model).where(
            self.model.id.in_(ids), self.model.organization_id == self.organization_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list(self) -> list[ModelType]:
        """Fetch all records for this repository's organization, newest first."""
        stmt = (
            select(self.model)
            .where(self.model.organization_id == self.organization_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs) -> ModelType:
        """Create a new record, stamped with this repository's organization."""
        kwargs.pop("organization_id", None)
        return await super().create(organization_id=self.organization_id, **kwargs)

    async def update(self, id, **kwargs) -> ModelType | None:
        """Update an existing record by id. Never lets a caller re-parent a
        row to another organization via a stray `organization_id` kwarg."""
        kwargs.pop("organization_id", None)
        return await super().update(id, **kwargs)
