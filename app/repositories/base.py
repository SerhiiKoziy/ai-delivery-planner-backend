"""Generic base repository providing common CRUD method signatures."""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """Generic repository over a single SQLAlchemy model."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get(self, id: str) -> ModelType | None:
        """Fetch a single record by id."""
        raise NotImplementedError

    async def list(self) -> list[ModelType]:
        """Fetch all records."""
        raise NotImplementedError

    async def create(self, **kwargs) -> ModelType:
        """Create and persist a new record."""
        raise NotImplementedError

    async def update(self, id: str, **kwargs) -> ModelType:
        """Update an existing record by id."""
        raise NotImplementedError

    async def delete(self, id: str) -> None:
        """Delete a record by id."""
        raise NotImplementedError
