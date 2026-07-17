"""Auth API routes.

Handles user registration, login, and JWT refresh. Business logic lives in
core.security / a future auth service — this module only wires HTTP.
"""

from fastapi import APIRouter

from app.schemas.auth import Token, UserCreate, UserLogin

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=Token)
async def register(payload: UserCreate) -> Token:
    """Create a new user account and return an access/refresh token pair."""
    raise NotImplementedError


@router.post("/login", response_model=Token)
async def login(payload: UserLogin) -> Token:
    """Authenticate a user and return an access/refresh token pair."""
    raise NotImplementedError


@router.post("/refresh", response_model=Token)
async def refresh(refresh_token: str) -> Token:
    """Exchange a valid refresh token for a new access token."""
    raise NotImplementedError
