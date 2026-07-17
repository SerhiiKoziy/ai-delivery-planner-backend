"""Shared FastAPI dependencies: DB session and current-user resolution."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session."""
    raise NotImplementedError


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Resolve the current authenticated user from a bearer JWT."""
    raise NotImplementedError
