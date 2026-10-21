"""Turn an IBM Runtime job (or a local fake-backend job) into plain JSON-able
fields for the ledger. Everything here is defensive: a field IBM doesn't
return for a given job type/version is simply left out, never an error.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MAX_MEMORY_SHOTS = 100_000

# IBM job statuses (JobStatus enum names / runtime strings) grouped by meaning
DONE_STATUSES = {"DONE"}
FAILED_STATUSES = {"ERROR", "FAILED"}
CANCELLED_STATUSES = {"CANCELLED"}


@dataclass
class ExtractedResult:
    counts: dict[str, int]
    memory: list[str]
    result_metadata: dict = field(default_factory=dict)
    job_metrics: dict = field(default_factory=dict)
    ibm_status: str | None = None
    qpu_seconds: float | None = None
    queue_ms: float | None = None
    execution_ms: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    session_id: str | None = None


def status_name(job) -> str:
    status = job.status()
    return getattr(status, "name", str(status)).upper()


def _parse_ts(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _jsonable(value: Any, depth: int = 0) -> Any:
    """Best-effort conversion of IBM metadata (datetimes, numpy, enums) to JSON."""
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, depth + 1) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def extract(job, result, *, register: str = "meas") -> ExtractedResult:
    """Pull counts, per-shot memory, metadata, timestamps and usage from a
    finished SamplerV2 job/result (PUB 0)."""
    pub = result[0]
    bits = getattr(pub.data, register)
    counts = {k: int(v) for k, v in bits.get_counts().items()}
    memory = list(bits.get_bitstrings())[:MAX_MEMORY_SHOTS]

    extracted = ExtractedResult(
        counts=counts,
        memory=memory,
        result_metadata=_jsonable(
            {"result": getattr(result, "metadata", {}), "pub": getattr(pub, "metadata", {})}
        ),
    )
    try:
        extracted.ibm_status = status_name(job)
    except Exception:
        pass
    try:
        session_id = job.session_id  # a property on RuntimeJobV2; absent on local jobs
        extracted.session_id = str(session_id) if session_id else None
    except Exception:
        pass

    metrics = None
    if hasattr(job, "metrics"):
        try:
            metrics = job.metrics()
        except Exception:
            metrics = None
    if metrics:
        extracted.job_metrics = _jsonable(metrics)
        stamps = metrics.get("timestamps", {}) or {}
        created = _parse_ts(stamps.get("created"))
        extracted.started_at = _parse_ts(stamps.get("running"))
        extracted.finished_at = _parse_ts(stamps.get("finished"))
        if created and extracted.started_at:
            extracted.queue_ms = (extracted.started_at - created).total_seconds() * 1000
        if extracted.started_at and extracted.finished_at:
            extracted.execution_ms = (
                extracted.finished_at - extracted.started_at
            ).total_seconds() * 1000
        usage = metrics.get("usage", {}) or {}
        seconds = usage.get("quantum_seconds", usage.get("seconds"))
        extracted.qpu_seconds = float(seconds) if seconds is not None else None
    if extracted.qpu_seconds is None and hasattr(job, "usage"):
        try:
            extracted.qpu_seconds = float(job.usage())
        except Exception:
            pass
    return extracted


def wait_and_extract(job, timeout_seconds: float) -> tuple[ExtractedResult, float]:
    """Block until the job finishes (or raise TimeoutError); returns the
    extracted result and how long we waited."""
    started = time.perf_counter()
    try:
        try:
            result = job.result(timeout=timeout_seconds)
        except TypeError:  # local fake-backend jobs take no timeout argument
            result = job.result()
    except Exception as exc:
        name = type(exc).__name__.lower()
        if "timeout" in name or "timed out" in str(exc).lower():
            raise TimeoutError(str(exc)) from exc
        raise
    return extract(job, result), (time.perf_counter() - started) * 1000
