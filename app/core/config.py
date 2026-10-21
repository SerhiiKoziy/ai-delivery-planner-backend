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

    # Quantum territory planning (app.services.territory). Each bisection
    # step is a QUBO over at most QUANTUM_MAX_QUBITS micro-zones — the
    # built-in NumPy statevector simulator is 2^n memory, and real hardware
    # turns deep circuits into noise well before ~20 qubits for this problem.
    QUANTUM_MAX_QUBITS: int = 12
    QUANTUM_DEFAULT_SHOTS: int = 2048
    QUANTUM_DEFAULT_QAOA_REPS: int = 2
    # IBM Quantum Platform. Empty token = the "ibm_quantum" solver is
    # unavailable (the simulator and the local IBM emulator still work).
    IBM_QUANTUM_TOKEN: str = ""
    IBM_QUANTUM_INSTANCE: str = ""
    IBM_QUANTUM_CHANNEL: str = "ibm_quantum_platform"
    IBM_QUANTUM_BACKEND: str = ""  # empty = least busy operational device
    IBM_QUANTUM_TIMEOUT_SECONDS: int = 300
    # Per-organization monthly cap on real QPU time, below the free Open
    # Plan's allowance so one tenant can't burn the whole account.
    IBM_QUANTUM_MONTHLY_BUDGET_SECONDS: float = 540.0
    # Also run every real-QPU circuit locally on Aer with the device's own
    # noise model and store it in the quantum ledger ("model vs reality").
    # Costs ~tens of CPU-seconds per 12-qubit job, so off by default.
    QUANTUM_LEDGER_NOISE_MODEL_PREDICTION: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
