"""Auth API routes.

Handles user registration, login, and JWT refresh. Business logic lives in
core.security / a future auth service — this module only wires HTTP.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_organization_repository, get_user_repository
from app.core.rate_limiting import login_rate_limiter, register_rate_limiter
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_email_verification_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    EmailVerificationRequest,
    RefreshRequest,
    RegisterResponse,
    Token,
    UserCreate,
    UserLogin,
)
from app.services.notifications.email import send_verification_email

router = APIRouter(tags=["auth"])


def _issue_tokens(user_id: uuid.UUID) -> Token:
    subject = str(user_id)
    return Token(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_rate_limiter)],
)
async def register(
    payload: UserCreate,
    user_repo: UserRepository = Depends(get_user_repository),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> RegisterResponse:
    """Create a new user account (with its own new organization), unverified,
    and email a verification link. One user = one organization: there's no
    invite/join-existing-org flow, so every registration starts a fresh
    tenant named after the user's email.

    No tokens are issued here — the account can't log in
    (see `login`) until `verify_email` confirms the address.
    """
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
        is_verified=False,
        created_at=now,
        updated_at=now,
    )
    verification_token = create_email_verification_token(str(user.id))
    await send_verification_email(user.email, verification_token)
    return RegisterResponse(user_id=str(user.id), email=user.email)


@router.post("/verify-email", response_model=Token)
async def verify_email(
    payload: EmailVerificationRequest,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Token:
    """Redeem an email-verification token: activates the account and, since
    that's the point where we know the address is real, immediately logs the
    user in (rather than making them separately call `login` next)."""
    invalid_token_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired verification token",
    )
    try:
        claims = decode_token(payload.token)
    except InvalidTokenError as exc:
        raise invalid_token_error from exc

    if claims.get("type") != "email_verification":
        raise invalid_token_error

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise invalid_token_error from exc

    user = await user_repo.get(user_id)
    if user is None:
        raise invalid_token_error

    if not user.is_verified:
        user = await user_repo.update(user.id, is_verified=True)

    return _issue_tokens(user.id)


@router.post("/login", dependencies=[Depends(login_rate_limiter)], response_model=Token)
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

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in",
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
