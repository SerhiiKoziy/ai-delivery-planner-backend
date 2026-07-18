"""AI API routes.

Wraps services.ai (OpenAI-backed) for address cleaning / note parsing /
duplicate detection on import, and for conversational route Q&A and
mid-route replanning. The LLM never performs route optimization itself.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from openai import AsyncOpenAI

from app.core.dependencies import (
    DeliveryAnalysisService,
    RouteChatService,
    RouteExplainerService,
    get_ai_model,
    get_chat_message_repository,
    get_current_user,
    get_delivery_analysis_service,
    get_delivery_repository,
    get_route_chat_service,
    get_route_context,
    get_route_explainer_service,
    get_route_optimizer_service,
    get_route_repository,
    get_route_stop_repository,
)
from app.repositories.chat_message_repository import ChatMessageRepository
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.route_stop_repository import RouteStopRepository
from app.schemas.ai import (
    ChatMessageRead,
    ChatRequest,
    ChatResponse,
    DeliveryAnalysisResult,
    ExplainRequest,
    ExplainResponse,
    ReplanEventType,
    ReplanRequest,
    ReplanResult,
)
from app.services.ai.client import get_openai_client
from app.services.ai.replanner import build_stop_diff, explain_replan, interpret_replan_message, parse_hhmm
from app.services.importers.csv_importer import parse_csv
from app.services.importers.excel_importer import parse_excel
from app.services.importers.mapping import normalize_row
from app.services.route_optimizer.service import RouteOptimizerService

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
    chat_message_repo: ChatMessageRepository = Depends(get_chat_message_repository),
    service: RouteChatService = Depends(get_route_chat_service),
) -> ChatResponse:
    """Conversational Q&A over route/delivery data, including replanning suggestions.

    Prior turns for this route are persisted and replayed as context on every
    call, so the conversation stays coherent across requests.
    """
    route, deliveries = await get_route_context(
        payload.route_id, route_repo, route_stop_repo, delivery_repo
    )
    history = await chat_message_repo.list_by_route(payload.route_id)
    history_turns = [(m.role, m.content) for m in history]

    reply = await service.run(payload.message, route, deliveries, history_turns)

    # Distinct timestamps (rather than one shared `now`) keep replay order
    # deterministic regardless of the DB's timestamp precision.
    now = datetime.now(UTC)
    await chat_message_repo.create(
        route_id=payload.route_id, role="user", content=payload.message, created_at=now
    )
    await chat_message_repo.create(
        route_id=payload.route_id,
        role="assistant",
        content=reply,
        created_at=now + timedelta(microseconds=1),
    )

    return ChatResponse(reply=reply)


@router.get("/chat/{route_id}/history", response_model=list[ChatMessageRead])
async def chat_history(
    route_id: uuid.UUID,
    chat_message_repo: ChatMessageRepository = Depends(get_chat_message_repository),
) -> list[ChatMessageRead]:
    """Return a route's persisted chat history, oldest first."""
    messages = await chat_message_repo.list_by_route(route_id)
    return [ChatMessageRead.model_validate(m) for m in messages]


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


@router.post("/replan", response_model=ReplanResult)
async def replan(
    payload: ReplanRequest,
    route_repo: RouteRepository = Depends(get_route_repository),
    route_stop_repo: RouteStopRepository = Depends(get_route_stop_repository),
    delivery_repo: DeliveryRepository = Depends(get_delivery_repository),
    optimizer: RouteOptimizerService = Depends(get_route_optimizer_service),
    client: AsyncOpenAI = Depends(get_openai_client),
    model: str = Depends(get_ai_model),
) -> ReplanResult:
    """Interpret a free-text dispatcher message and re-run the optimizer accordingly.

    Resolves the affected delivery deterministically from the small integer
    `affected_stop_sequence` the model is asked to return (never a UUID),
    calls `RouteOptimizerService.replan()`, and returns a before/after diff
    plus a natural-language explanation. At most 2 OpenAI calls are made:
    one to interpret the message, and (only if recognized) one to explain
    the resulting diff.
    """
    route, _ = await get_route_context(payload.route_id, route_repo, route_stop_repo, delivery_repo)

    all_stops_before = await route_stop_repo.list_by_route(payload.route_id)
    pending_stops = [stop for stop in all_stops_before if stop.status == "pending"]
    pending_delivery_ids = [stop.delivery_id for stop in pending_stops]
    pending_deliveries_by_id = {
        d.id: d
        for d in (
            await delivery_repo.get_many(pending_delivery_ids) if pending_delivery_ids else []
        )
    }

    def _window_str(value) -> str | None:
        return value.strftime("%H:%M") if value else None

    pending_stops_context = [
        {
            "sequence": stop.sequence,
            "customer_name": pending_deliveries_by_id[stop.delivery_id].customer_name,
            "address": pending_deliveries_by_id[stop.delivery_id].address,
            "delivery_window_start": _window_str(
                pending_deliveries_by_id[stop.delivery_id].delivery_window_start
            ),
            "delivery_window_end": _window_str(
                pending_deliveries_by_id[stop.delivery_id].delivery_window_end
            ),
            "priority": pending_deliveries_by_id[stop.delivery_id].priority.value,
        }
        for stop in pending_stops
    ]

    interpretation = await interpret_replan_message(
        payload.message, pending_stops_context, client=client, model=model
    )

    def _unrecognized_result(interpretation) -> ReplanResult:
        return ReplanResult(
            route_id=payload.route_id,
            interpretation=interpretation,
            applied=False,
            diff=[],
            total_distance_km_before=route.total_distance_km,
            total_distance_km_after=route.total_distance_km,
            total_duration_minutes_before=route.total_duration_minutes,
            total_duration_minutes_after=route.total_duration_minutes,
            time_saved_minutes=0.0,
            explanation=interpretation.summary,
        )

    if interpretation.event_type == ReplanEventType.UNRECOGNIZED:
        return _unrecognized_result(interpretation)

    resolved_stop = next(
        (s for s in pending_stops if s.sequence == interpretation.affected_stop_sequence), None
    )

    excluded_delivery_ids = None
    window_overrides = None
    start_delay_minutes = 0
    new_window_start = None
    new_window_end = None
    resolved_delivery_id = None

    if interpretation.event_type in (
        ReplanEventType.CUSTOMER_UNREACHABLE,
        ReplanEventType.DELIVERY_CANCELLED,
        ReplanEventType.DELIVERY_RESCHEDULED,
    ):
        # interpret_replan_message() already validates affected_stop_sequence
        # against the pending-stops list it was given; this is a defensive
        # re-check against the same data, not expected to ever fire.
        if resolved_stop is None:  # pragma: no cover - defensive
            interpretation = interpretation.model_copy(
                update={
                    "event_type": ReplanEventType.UNRECOGNIZED,
                    "summary": "Could not identify the affected delivery/stop from the message.",
                }
            )
            return _unrecognized_result(interpretation)
        resolved_delivery_id = resolved_stop.delivery_id

    if interpretation.event_type in (
        ReplanEventType.CUSTOMER_UNREACHABLE,
        ReplanEventType.DELIVERY_CANCELLED,
    ):
        excluded_delivery_ids = [resolved_delivery_id]
    elif interpretation.event_type == ReplanEventType.DELIVERY_RESCHEDULED:
        parsed_start = parse_hhmm(interpretation.new_window_start)
        parsed_end = parse_hhmm(interpretation.new_window_end)
        if parsed_start is None or parsed_end is None:
            interpretation = interpretation.model_copy(
                update={
                    "event_type": ReplanEventType.UNRECOGNIZED,
                    "summary": "Could not parse the requested new delivery time window.",
                }
            )
            return _unrecognized_result(interpretation)
        window_overrides = {resolved_delivery_id: (parsed_start, parsed_end)}
        new_window_start = interpretation.new_window_start
        new_window_end = interpretation.new_window_end
    elif interpretation.event_type == ReplanEventType.DRIVER_DELAYED:
        start_delay_minutes = interpretation.delay_minutes or 0

    try:
        outcome = await optimizer.replan(
            payload.route_id,
            excluded_delivery_ids=excluded_delivery_ids,
            window_overrides=window_overrides,
            start_delay_minutes=start_delay_minutes,
            persist=not payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    all_delivery_ids = [stop.delivery_id for stop in outcome.stops_before]
    customer_names = {
        d.id: d.customer_name
        for d in (await delivery_repo.get_many(all_delivery_ids) if all_delivery_ids else [])
    }

    diff = build_stop_diff(
        outcome.stops_before,
        outcome.stops_after,
        customer_names,
        interpretation.event_type,
        rescheduled_delivery_id=(
            resolved_delivery_id
            if interpretation.event_type == ReplanEventType.DELIVERY_RESCHEDULED
            else None
        ),
        new_window_start=new_window_start,
        new_window_end=new_window_end,
    )
    changed_diff = [entry for entry in diff if entry.change != "unchanged"]

    distance_after = outcome.route.total_distance_km
    duration_after = outcome.route.total_duration_minutes

    explanation = await explain_replan(
        interpretation,
        changed_diff,
        distance_before=route.total_distance_km,
        distance_after=distance_after,
        duration_before=route.total_duration_minutes,
        duration_after=duration_after,
        client=client,
        model=model,
    )

    return ReplanResult(
        route_id=payload.route_id,
        interpretation=interpretation,
        applied=True,
        diff=diff,
        total_distance_km_before=route.total_distance_km,
        total_distance_km_after=distance_after,
        total_duration_minutes_before=route.total_duration_minutes,
        total_duration_minutes_after=duration_after,
        time_saved_minutes=float(route.total_duration_minutes - duration_after),
        explanation=explanation,
    )
