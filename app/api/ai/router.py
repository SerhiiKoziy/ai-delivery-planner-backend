"""AI API routes.

Wraps services.ai (OpenAI-backed) for address cleaning / note parsing /
duplicate detection on import, and for conversational route Q&A and
mid-route replanning. The LLM never performs route optimization itself.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user

router = APIRouter(tags=["ai"], dependencies=[Depends(get_current_user)])


@router.post("/analyze")
async def analyze_deliveries() -> dict:
    """Analyze an imported delivery list: clean addresses, parse notes, flag duplicates."""
    raise NotImplementedError


@router.post("/chat")
async def chat() -> dict:
    """Conversational Q&A over route/delivery data, including replanning suggestions."""
    raise NotImplementedError
