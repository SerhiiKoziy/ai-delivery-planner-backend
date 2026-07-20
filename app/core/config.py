"""Application settings, loaded from environment variables / .env.

See .env.example at the repo root for the full list of expected variables.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "AI Delivery Planner"
    ENVIRONMENT: str = "local"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_delivery_planner"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # Third-party APIs
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    GOOGLE_MAPS_API_KEY: str = ""

    # Email (Gmail SMTP) — GMAIL_ADDRESS/GMAIL_APP_PASSWORD empty means "no
    # provider configured", in which case the verification link is only
    # logged, never sent. GMAIL_ADDRESS is both the SMTP login and the
    # "From" address — Gmail rejects sending as anyone else unless a "Send
    # As" alias is configured on the account, so keeping one field avoids a
    # config combination that would silently fail.
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
