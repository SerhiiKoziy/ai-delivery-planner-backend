"""OpenAI client wrapper shared by the AI services."""

from openai import AsyncOpenAI

from app.core.config import get_settings


def get_openai_client() -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client."""
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
