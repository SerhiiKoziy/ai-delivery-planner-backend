"""Auth request/response schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.roles import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterResponse(BaseModel):
    """Returned by POST /auth/register — no tokens yet: the account is
    unverified until POST /auth/verify-email is called with the token
    "emailed" to `email`."""

    user_id: str
    email: EmailStr
    message: str = "Verification email sent. Please verify your email before logging in."


class EmailVerificationRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Same answer whether or not the email is registered, so the endpoint
    can't be used to find out who has an account."""

    message: str = "If an account with this email exists, we've sent a password reset link."


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class CurrentUserRead(BaseModel):
    """GET /auth/me — who is logged in and what they may see (role)."""

    id: str
    email: EmailStr
    organization_id: str = Field(alias="organizationId")
    role: UserRole
    is_verified: bool = Field(alias="isVerified")

    model_config = ConfigDict(populate_by_name=True)
