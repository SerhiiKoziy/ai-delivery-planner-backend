"""Auth API routes.

Handles user registration, login, JWT refresh and the forgot/reset password
flow. Business logic lives in core.security / a future auth service — this
module only wires HTTP.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.dependencies import (
    get_current_user,
    get_organization_repository,
    get_user_repository,
)
from app.core.rate_limiting import (
    forgot_password_rate_limiter,
    login_rate_limiter,
    register_rate_limiter,
)
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_reset_token_matches,
    verify_password,
)
from app.db.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    CurrentUserRead,
    EmailVerificationRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    RefreshRequest,
    RegisterResponse,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserLogin,
)
from app.services.notifications.email import send_password_reset_email, send_verification_email

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


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    dependencies=[Depends(forgot_password_rate_limiter)],
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    user_repo: UserRepository = Depends(get_user_repository),
) -> ForgotPasswordResponse:
    """Email a password-reset link if the address belongs to an account.

    The response is identical either way, and the email goes out in the
    background, so neither the body nor the response time tells a caller
    whether the email is registered."""
    user = await user_repo.get_by_email(payload.email)
    if user is not None:
        token = create_password_reset_token(str(user.id), user.hashed_password)
        background_tasks.add_task(send_password_reset_email, user.email, token)
    return ForgotPasswordResponse()


@router.post("/reset-password", response_model=Token)
async def reset_password(
    payload: ResetPasswordRequest,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Token:
    """Redeem a reset token: set the new password and log the user in.

    The token only works for the password it was issued against, so it's
    single-use. Following the emailed link also proves the inbox is real,
    so an unverified account becomes verified here."""
    invalid_token_error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This password reset link is invalid or has expired",
    )
    try:
        claims = decode_token(payload.token)
    except InvalidTokenError as exc:
        raise invalid_token_error from exc

    if claims.get("type") != "password_reset":
        raise invalid_token_error

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise invalid_token_error from exc

    user = await user_repo.get(user_id)
    if user is None or not password_reset_token_matches(claims, user.hashed_password):
        raise invalid_token_error

    user = await user_repo.update(
        user.id,
        hashed_password=hash_password(payload.new_password),
        is_verified=True,
        updated_at=datetime.now(UTC),
    )
    return _issue_tokens(user.id)


@router.get("/me", response_model=CurrentUserRead)
async def me(current_user: User = Depends(get_current_user)) -> CurrentUserRead:
    """Return the logged-in user, including their role, so the frontend can
    decide which features (e.g. the admin-only quantum ones) to show."""
    return CurrentUserRead(
        id=str(current_user.id),
        email=current_user.email,
        organization_id=str(current_user.organization_id),
        role=current_user.role,
        is_verified=current_user.is_verified,
    )


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
