"""Password hashing and JWT creation/verification.

Stub implementations only — wire up passlib/python-jose here.
"""

from datetime import timedelta

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage."""
    raise NotImplementedError


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against its stored hash."""
    raise NotImplementedError


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token for the given subject (user id)."""
    raise NotImplementedError


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT refresh token for the given subject (user id)."""
    raise NotImplementedError


def decode_token(token: str) -> dict:
    """Decode and verify a JWT, returning its claims."""
    raise NotImplementedError
