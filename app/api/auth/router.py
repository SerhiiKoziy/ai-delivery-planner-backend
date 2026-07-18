"""Auth API routes.

Handles user registration, login, and JWT refresh. Business logic lives in
core.security / a future auth service — this module only wires HTTP.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_organization_repository, get_user_repository
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RefreshRequest, Token, UserCreate, UserLogin

router = APIRouter(tags=["auth"])


def _issue_tokens(user_id: uuid.UUID) -> Token:
    subject = str(user_id)
    return Token(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    user_repo: UserRepository = Depends(get_user_repository),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> Token:
    """Create a new user account (with its own new organization) and return
    an access/refresh token pair. One user = one organization: there's no
    invite/join-existing-org flow, so every registration starts a fresh
    tenant named after the user's email."""
    existing = await user_repo.get_by_email(payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    now = datetime.now(UTC)
    organization = await org_repo.create(
        name=f"{payload.email}'s Organization",
        created_at=now,
        updated_at=now,
    )
    user = await user_repo.create(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        organization_id=organization.id,
        created_at=now,
        updated_at=now,
    )
    return _issue_tokens(user.id)


@router.post("/login", response_model=Token)
async def login(
    payload: UserLogin,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Token:
    """Authenticate a user and return an access/refresh token pair."""
    user = await user_repo.get_by_email(payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    return _issue_tokens(user.id)


@router.post("/refresh", response_model=Token)
async def refresh(
    payload: RefreshRequest,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Token:
    """Exchange a valid refresh token for a new access/refresh token pair."""
    invalid_token_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )
    try:
        claims = decode_token(payload.refresh_token)
    except InvalidTokenError as exc:
        raise invalid_token_error from exc

    if claims.get("type") != "refresh":
        raise invalid_token_error

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise invalid_token_error from exc

    user = await user_repo.get(user_id)
    if user is None:
        raise invalid_token_error

    return _issue_tokens(user.id)
