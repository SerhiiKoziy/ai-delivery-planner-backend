"""FastAPI application factory and entrypoint.

Run locally with: uvicorn app.main:app --reload
"""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai.router import router as ai_router
from app.api.auth.router import router as auth_router
from app.api.dashboard.router import router as dashboard_router
from app.api.deliveries.router import router as deliveries_router
from app.api.depots.router import router as depots_router
from app.api.drivers.router import router as drivers_router
from app.api.organizations.router import router as organizations_router
from app.api.quantum.router import router as quantum_router
from app.api.routes.router import router as routes_router
from app.api.territories.router import router as territories_router
from app.api.vehicles.router import router as vehicles_router
from app.core.config import get_settings
from app.core.dependencies import (
    get_current_user,
    get_ibm_runtime_service_factory,
    get_quantum_ledger,
)
from app.core.error_handlers import register_exception_handlers
from app.quantum_ledger import build_ledger_router

settings = get_settings()

API_V1_PREFIX = "/api/v1"

QUANTUM_LAB_PAGE = Path(__file__).parent / "web" / "quantum_lab.html"


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title=settings.APP_NAME)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(auth_router, prefix=f"{API_V1_PREFIX}/auth")
    app.include_router(deliveries_router, prefix=f"{API_V1_PREFIX}/deliveries")
    app.include_router(depots_router, prefix=f"{API_V1_PREFIX}/depots")
    app.include_router(routes_router, prefix=f"{API_V1_PREFIX}/routes")
    app.include_router(drivers_router, prefix=f"{API_V1_PREFIX}/drivers")
    app.include_router(vehicles_router, prefix=f"{API_V1_PREFIX}/vehicles")
    app.include_router(ai_router, prefix=f"{API_V1_PREFIX}/ai")
    app.include_router(dashboard_router, prefix=f"{API_V1_PREFIX}/dashboard")
    app.include_router(organizations_router, prefix=f"{API_V1_PREFIX}/organizations")
    app.include_router(territories_router, prefix=f"{API_V1_PREFIX}/territories")
    # Ledger before the generic quantum router so /quantum/ledger/* isn't
    # shadowed; visible to every logged-in user for now (admin-only later).
    app.include_router(
        build_ledger_router(get_quantum_ledger, get_ibm_runtime_service_factory),
        prefix=f"{API_V1_PREFIX}/quantum/ledger",
        dependencies=[Depends(get_current_user)],
    )
    app.include_router(quantum_router, prefix=f"{API_V1_PREFIX}/quantum")

    @app.get("/quantum-lab", response_class=HTMLResponse, include_in_schema=False)
    async def quantum_lab() -> HTMLResponse:
        """Self-contained "Quantum lab" tab (vanilla JS over /api/v1/quantum and
        /territories). The page itself is public; every API call it makes
        carries the user's bearer token."""
        return HTMLResponse(QUANTUM_LAB_PAGE.read_text(encoding="utf-8"))

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
