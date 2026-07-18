"""AI API routes.

Wraps services.ai (OpenAI-backed) for address cleaning / note parsing /
duplicate detection on import, and for conversational route Q&A and
mid-route replanning. The LLM never performs route optimization itself.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.core.dependencies import (
    DeliveryAnalysisService,
    RouteChatService,
    RouteExplainerService,
    get_current_user,
    get_delivery_analysis_service,
    get_delivery_repository,
    get_route_chat_service,
    get_route_context,
    get_route_explainer_service,
    get_route_repository,
    get_route_stop_repository,
)
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    DeliveryAnalysisResult,
    ExplainRequest,
    ExplainResponse,
)
from app.services.importers.csv_importer import parse_csv
from app.services.importers.excel_importer import parse_excel
from app.services.importers.mapping import normalize_row

router = APIRouter(tags=["ai"], dependencies=[Depends(get_current_user)])


@router.post("/analyze", response_model=DeliveryAnalysisResult)
async def analyze_deliveries(
    file: UploadFile,
    service: DeliveryAnalysisService = Depends(get_delivery_analysis_service),
) -> DeliveryAnalysisResult:
    """Analyze an imported delivery list: clean addresses, parse notes, flag duplicates.

    A preview step over an uploaded Excel/CSV file — runs before geocoding/import
    commit and does not persist anything.
    """
    content = await file.read()
    filename = (file.filename or "").lower()
    if filename.endswith(".csv"):
        raw_rows = parse_csv(content)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        raw_rows = parse_excel(content)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension for import: {file.filename!r}",
        )

    try:
        rows = [normalize_row(raw_row) for raw_row in raw_rows]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await service.run(rows)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    route_repo: RouteRepository = Depends(get_route_repository),
    route_stop_repo: RouteStopRepository = Depends(get_route_stop_repository),
    delivery_repo: DeliveryRepository = Depends(get_delivery_repository),
    service: RouteChatService = Depends(get_route_chat_service),
) -> ChatResponse:
    """Conversational Q&A over route/delivery data, including replanning suggestions."""
    route, deliveries = await get_route_context(
        payload.route_id, route_repo, route_stop_repo, delivery_repo
    )
    reply = await service.run(payload.message, route, deliveries)
    return ChatResponse(reply=reply)


@router.post("/explain", response_model=ExplainResponse)
async def explain(
    payload: ExplainRequest,
    route_repo: RouteRepository = Depends(get_route_repository),
    route_stop_repo: RouteStopRepository = Depends(get_route_stop_repository),
    delivery_repo: DeliveryRepository = Depends(get_delivery_repository),
    service: RouteExplainerService = Depends(get_route_explainer_service),
) -> ExplainResponse:
    """Generate a natural-language explanation of why a route was sequenced this way."""
    route, deliveries = await get_route_context(
        payload.route_id, route_repo, route_stop_repo, delivery_repo
    )
    explanation = await service.run(route, deliveries)
    return ExplainResponse(explanation=explanation)
