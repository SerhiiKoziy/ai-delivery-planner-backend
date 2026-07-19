"""Auth request/response schemas."""

from pydantic import BaseModel, EmailStr


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
