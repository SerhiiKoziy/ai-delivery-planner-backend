# AI Delivery Planner — Backend

## What this is

AI Delivery Planner is a SaaS tool for small businesses that run their own local
deliveries. Businesses import a delivery list (Excel/CSV upload or manual entry),
and the system prepares it for routing: an LLM (OpenAI) cleans up messy addresses,
parses free-text notes into structured fields, and flags likely duplicate entries.
Cleaned addresses are then geocoded, and **Google OR-Tools** — not the LLM — solves
the actual vehicle routing problem, producing optimized multi-driver routes that
respect delivery time windows, priorities, vehicle capacity, and driver working
hours. On top of that, an AI chat lets users ask questions about a route ("why is
this stop last?") and request AI-assisted replanning mid-route.

**Key point on AI usage:** the LLM handles language tasks (address cleanup, note
parsing, duplicate detection, natural-language explanations, chat). It never
computes routes itself — route optimization is deterministic, constraint-based
solving via OR-Tools.

## Architecture

```
React (frontend) → Axios → FastAPI → Service Layer → Repository Layer → PostgreSQL
                                  │
                                  ├─ services.route_optimizer (Google OR-Tools)
                                  ├─ services.geocoding (Google Maps Geocoding API)
                                  ├─ services.ai (OpenAI: cleanup, parsing, chat, explanations)
                                  └─ services.importers (Excel/CSV parsing)
```

The codebase follows a feature-based, layered ("Clean Architecture"-flavored)
structure:

- `app/api/*` — FastAPI routers, one package per feature (auth, deliveries,
  routes, drivers, vehicles, ai, dashboard). HTTP-only concerns.
- `app/core` — settings, security (JWT/password hashing), logging, shared
  dependencies.
- `app/db` — SQLAlchemy models and async session management; Alembic
  migrations live under `app/db/migrations`.
- `app/services` — business logic, isolated from HTTP and persistence
  details (route optimization, geocoding, AI, importers, notifications).
- `app/repositories` — persistence access, isolating services from raw
  SQLAlchemy queries.
- `app/schemas` — Pydantic request/response contracts.
- `app/workers` — Celery app and background tasks for long-running jobs
  (optimization, AI analysis).
- `app/tests` — pytest suite.

This is currently a **scaffold**: stub signatures and docstrings, not working
business logic, aside from `GET /health` and its test.

## Stack

- **API**: FastAPI, Uvicorn
- **DB**: PostgreSQL via SQLAlchemy (async) + asyncpg, Alembic for migrations
- **Auth**: JWT (python-jose) + passlib (bcrypt)
- **Background jobs**: Celery + Redis
- **AI**: OpenAI API
- **Routing**: Google OR-Tools
- **Geocoding**: Google Maps Geocoding API
- **Imports**: pandas, openpyxl
- **Testing/linting**: pytest, pytest-asyncio, ruff

## Local development

### Option 1: virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest
```

### Option 2: Docker

```bash
docker build -t ai-delivery-planner-backend .
docker run --rm -p 8000:8000 --env-file .env ai-delivery-planner-backend
```

The API will be available at `http://localhost:8000`, with a health check at
`GET /health`.

## Related repositories

This repo is one of three siblings that together make up the project:

- `ai-delivery-planner-frontend` (local folder name: `AI-Planning-Assistant`)
- `ai-delivery-planner-backend` (this repo)
- `ai-delivery-planner-infra`
