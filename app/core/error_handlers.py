"""Centralized exception handlers so every API response — including ones
from bugs and third-party outages, not just deliberate `raise HTTPException`
calls — comes back as a clear, consistent `{"detail": "<readable string>"}`
JSON body.

Without these:
- An uncaught exception returns Starlette's default plain-text 500 body
  (not JSON at all), breaking every client that expects `response.data.detail`.
- A Pydantic validation error returns a nested
  `{"detail": [{"loc": [...], "msg": ..., "type": ...}]}` list, which a
  frontend can't display directly (it expects `detail` to be a plain string
  — see AI-Planning-Assistant's `getApiErrorMessage`).
- An OpenAI SDK failure (rate limit, outage, bad key) bubbles up as an
  unhandled exception, leaking the SDK's own error text to the client.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import OpenAIError

from app.core.plans import QuotaExceededError

logger = logging.getLogger("app.errors")


def _validation_error_message(exc: RequestValidationError) -> str:
    """Flatten Pydantic's per-field error list into one readable string,
    e.g. "email: field required; password: ensure this value has at least
    8 characters"."""
    parts = []
    for error in exc.errors():
        location = ".".join(
            str(segment) for segment in error["loc"] if segment not in ("body", "query", "path")
        )
        message = error["msg"]
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "Invalid request."


def register_exception_handlers(app: FastAPI) -> None:
    """Wire up every handler below onto `app`. Handlers are matched by
    exception type (most specific wins), so these coexist safely with
    FastAPI's own built-in handling of `HTTPException` — nothing here
    changes the behavior of the many existing `raise HTTPException(...)`
    call sites."""

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": _validation_error_message(exc)},
        )

    @app.exception_handler(QuotaExceededError)
    async def handle_quota_exceeded(request: Request, exc: QuotaExceededError) -> JSONResponse:
        # Safety net: DeliveryService's own call sites already catch this
        # explicitly and return the same shape — this covers any call site
        # that doesn't, so it gets a clean 403 instead of a 500.
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})

    @app.exception_handler(OpenAIError)
    async def handle_openai_error(request: Request, exc: OpenAIError) -> JSONResponse:
        # Outages/rate limits/auth issues from the OpenAI SDK must never
        # leak its own error text (which can include request ids and other
        # internal details) straight to the client.
        logger.error("OpenAI API error on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "The AI service is temporarily unavailable. Please try again shortly."
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Last-resort catch-all: never let a raw traceback or exception
        # message reach the client. The real error is still logged here for
        # debugging (and, in local dev, still visible in the uvicorn console).
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong on our end. Please try again."},
        )
