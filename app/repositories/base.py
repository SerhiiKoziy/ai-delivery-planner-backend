"""Generic base repository providing common async CRUD operations."""

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
