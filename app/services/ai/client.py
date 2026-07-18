"""OpenAI client wrapper shared by the AI services."""

import json

from openai import AsyncOpenAI

from app.core.config import get_settings


def get_openai_client() -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client."""
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def create_structured_completion(
    client: AsyncOpenAI,
    *,
    model: str,
    messages: list[dict],
    schema_name: str,
    json_schema: dict,
) -> dict:
    """Call the chat completions API with a strict JSON schema response format.

    Returns the parsed JSON object from the model's response content. Generic
    and reusable across services.ai — callers supply their own schema/messages.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
                "strict": True,
            },
        },
    )
    content = response.choices[0].message.content
    return json.loads(content)
