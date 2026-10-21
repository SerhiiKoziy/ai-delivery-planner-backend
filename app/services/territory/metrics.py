"""Aggregates QuantumRun rows into the dashboard summary."""

from collections import Counter

import numpy as np

from app.db.models.quantum_run import QuantumRun
from app.schemas.quantum import QuantumSummary, SolverAvailability, TimingStats

TIMING_FIELDS = (
    "build_ms",
    "classical_ms",
    "optimize_ms",
    "transpile_ms",
    "queue_ms",
    "execution_ms",
    "total_ms",
)


def _timing(values: list[float]) -> TimingStats:
    if not values:
        return TimingStats(count=0)
    arr = np.array(values, dtype=float)
    return TimingStats(
        count=len(values),
        avg_ms=float(arr.mean()),
        p50_ms=float(np.percentile(arr, 50)),
        p95_ms=float(np.percentile(arr, 95)),
        max_ms=float(arr.max()),
    )


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def summarize_runs(
    runs: list[QuantumRun],
    *,
    qpu_seconds_this_month: float,
    qpu_monthly_budget_seconds: float,
    solvers: dict[str, dict],
) -> QuantumSummary:
    completed = [r for r in runs if r.status == "completed"]
    return QuantumSummary(
        total_runs=len(runs),
        runs_by_status=dict(Counter(r.status for r in runs)),
        runs_by_provider=dict(Counter(r.provider for r in runs)),
        quantum_matched_optimum_rate=(
            sum(r.chosen_source == "quantum" for r in completed) / len(completed)
            if completed
            else None
        ),
        avg_approximation_ratio=_mean(
            [r.approximation_ratio for r in completed if r.approximation_ratio is not None]
        ),
        avg_optimum_probability=_mean(
            [r.optimum_probability for r in completed if r.optimum_probability is not None]
        ),
        avg_uniform_optimum_probability=_mean(
            [
                r.details["uniform_optimum_probability"]
                for r in completed
                if "uniform_optimum_probability" in (r.details or {})
            ]
        ),
        avg_sampled_optimum_frequency=_mean(
            [
                r.sampled_optimum_frequency
                for r in completed
                if r.sampled_optimum_frequency is not None
            ]
        ),
        avg_lift_over_random=_mean(
            [
                r.sampled_optimum_frequency / r.uniform_optimum_probability
                for r in completed
                if r.sampled_optimum_frequency is not None and r.uniform_optimum_probability
            ]
        ),
        avg_random_hit_probability=_mean(
            [
                1 - (1 - r.uniform_optimum_probability) ** r.shots
                for r in completed
                if r.uniform_optimum_probability is not None
            ]
        ),
        total_shots=sum(r.shots for r in completed),
        timings={
            name: _timing([getattr(r, name) for r in runs if getattr(r, name) is not None])
            for name in TIMING_FIELDS
        },
        qpu_seconds_this_month=qpu_seconds_this_month,
        qpu_monthly_budget_seconds=qpu_monthly_budget_seconds,
        last_run_at=max((r.created_at for r in runs), default=None),
        solvers={name: SolverAvailability(**status) for name, status in solvers.items()},
    )
