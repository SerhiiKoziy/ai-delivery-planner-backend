"""Territory planning: split deliveries into stable per-vehicle zones by
recursive balanced bisection, optionally solving each bisection on a quantum
backend and logging every quantum interaction as a QuantumRun.

Every step ALWAYS also gets the exact classical optimum (brute force over
2^n, n ≤ QUANTUM_MAX_QUBITS). The quantum answer is used only when its best
sample is as good — so a plan is never worse than the classical baseline,
and each QuantumRun records how close the quantum sampler came.
"""

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from app.core.config import Settings
from app.db.models.territory_plan import TerritoryPlan
from app.quantum_ledger import QuantumLedger, ising_problem_from_arrays
from app.quantum_ledger.analysis import noise_model_counts
from app.quantum_ledger.runtime import run_qiskit, wait_until_done
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.quantum_run_repository import QuantumRunRepository
from app.repositories.territory_plan_repository import TerritoryPlanRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.territory import TerritoryPlanRequest
from app.services.territory.problem import (
    IsingProblem,
    Point,
    aggregate,
    build_bisection_ising,
    ising_energies,
)
from app.services.territory.providers import (
    IbmRuntimeProvider,
    NumpyStatevectorProvider,
    QuantumTimeoutError,
    qiskit_available,
    top_counts,
)
from app.services.territory.qaoa import logical_circuit_stats, optimize_parameters, probabilities

ENERGY_TOLERANCE = 1e-9


class SolverUnavailableError(Exception):
    """The requested solver can't run in this deployment (missing extra / token)."""


@dataclass
class _StepOutcome:
    side_a_point_ids: set[str]


def available_solvers(settings: Settings) -> dict[str, dict]:
    has_qiskit = qiskit_available()
    return {
        "classical": {"available": True, "reason": None},
        "quantum_simulator": {"available": True, "reason": None},
        "ibm_emulator": {
            "available": has_qiskit,
            "reason": None
            if has_qiskit
            else "install the `quantum` extra (qiskit, qiskit-aer, qiskit-ibm-runtime)",
        },
        "ibm_quantum": {
            "available": has_qiskit and bool(settings.IBM_QUANTUM_TOKEN),
            "reason": (
                None
                if has_qiskit and settings.IBM_QUANTUM_TOKEN
                else "set IBM_QUANTUM_TOKEN and install the `quantum` extra"
            ),
        },
    }


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _exact_classical(problem: IsingProblem) -> tuple[np.ndarray, int, float]:
    energies = ising_energies(problem)
    best = int(np.argmin(energies))
    return energies, best, float(energies[best])


def _approximation_ratio(value: float, energies: np.ndarray) -> float:
    span = float(energies.max() - energies.min())
    return 1.0 if span == 0 else float((energies.max() - value) / span)


class TerritoryService:
    def __init__(
        self,
        plan_repository: TerritoryPlanRepository,
        run_repository: QuantumRunRepository,
        delivery_repository: DeliveryRepository,
        vehicle_repository: VehicleRepository,
        settings: Settings,
        ledger: QuantumLedger | None = None,
    ) -> None:
        self.plan_repository = plan_repository
        self.run_repository = run_repository
        self.delivery_repository = delivery_repository
        self.vehicle_repository = vehicle_repository
        self.settings = settings
        # Durable record of every IBM job (what was sent / returned / CPU reference)
        self.ledger = ledger

    def _provider(self, solver: str):
        status = available_solvers(self.settings).get(solver)
        if status is None or not status["available"]:
            reason = status["reason"] if status else "unknown solver"
            raise SolverUnavailableError(f"Solver '{solver}' is unavailable: {reason}")
        if solver == "classical":
            return None
        if solver == "quantum_simulator":
            return NumpyStatevectorProvider()
        if solver == "ibm_emulator":
            return IbmRuntimeProvider(emulator=True)
        return IbmRuntimeProvider(
            emulator=False,
            token=self.settings.IBM_QUANTUM_TOKEN,
            instance=self.settings.IBM_QUANTUM_INSTANCE,
            channel=self.settings.IBM_QUANTUM_CHANNEL,
            backend_name=self.settings.IBM_QUANTUM_BACKEND,
        )

    async def create_plan(self, payload: TerritoryPlanRequest) -> TerritoryPlan:
        started = time.perf_counter()
        provider = self._provider(payload.solver)

        vehicles_by_id = {
            v.id: v for v in await self.vehicle_repository.get_many(payload.vehicle_ids)
        }
        vehicles = [
            vehicles_by_id[vid]
            for vid in dict.fromkeys(payload.vehicle_ids)
            if vid in vehicles_by_id
        ]
        if not vehicles:
            raise ValueError("No vehicles found for this organization")

        deliveries = await self.delivery_repository.get_many(payload.delivery_ids)
        geocoded = [d for d in deliveries if d.latitude is not None and d.longitude is not None]
        if not geocoded:
            raise ValueError("None of the requested deliveries is geocoded")

        points = [
            Point(
                id=str(d.id),
                latitude=d.latitude,
                longitude=d.longitude,
                load=max(d.weight_kg, 0.01) if payload.balance_by == "weight" else 1.0,
            )
            for d in geocoded
        ]

        plan = await self.plan_repository.create(
            status="running",
            solver=payload.solver,
            balance_by=payload.balance_by,
            num_zones=len(vehicles),
            num_deliveries=len(points),
            zones=[],
            metrics={},
        )

        assignment: dict[str, int] = {}
        try:
            await self._split(
                plan.id, points, list(range(len(vehicles))), "root", payload, provider, assignment
            )
        except Exception as exc:
            return await self.plan_repository.update(
                plan.id, status="failed", error=str(exc), total_ms=_ms(started)
            )

        zones, metrics = self._summarize(points, assignment, vehicles)
        runs = await self.run_repository.list_by_plan(plan.id)
        metrics["quantum_runs"] = len(runs)
        metrics["quantum_steps_used"] = sum(1 for r in runs if r.chosen_source == "quantum")
        metrics["skipped_not_geocoded"] = [str(d.id) for d in deliveries if d not in geocoded]
        return await self.plan_repository.update(
            plan.id, status="completed", zones=zones, metrics=metrics, total_ms=_ms(started)
        )

    async def _split(
        self,
        plan_id: uuid.UUID,
        points: list[Point],
        zone_indices: list[int],
        step: str,
        payload: TerritoryPlanRequest,
        provider,
        assignment: dict[str, int],
    ) -> None:
        if len(zone_indices) == 1 or len(points) <= 1:
            for p in points:
                assignment[p.id] = zone_indices[0]
            return

        zones_a = zone_indices[: len(zone_indices) // 2]
        zones_b = zone_indices[len(zone_indices) // 2 :]
        outcome = await self._solve_step(
            plan_id, points, len(zones_a) / len(zone_indices), step, payload, provider
        )
        side_a = [p for p in points if p.id in outcome.side_a_point_ids]
        side_b = [p for p in points if p.id not in outcome.side_a_point_ids]
        child = "" if step == "root" else step
        await self._split(plan_id, side_a, zones_a, child + "A", payload, provider, assignment)
        await self._split(plan_id, side_b, zones_b, child + "B", payload, provider, assignment)

    async def _solve_step(
        self,
        plan_id: uuid.UUID,
        points: list[Point],
        target_fraction: float,
        step: str,
        payload: TerritoryPlanRequest,
        provider,
    ) -> _StepOutcome:
        step_started = time.perf_counter()
        t0 = time.perf_counter()
        nodes = await asyncio.to_thread(aggregate, points, self.settings.QUANTUM_MAX_QUBITS)
        problem = await asyncio.to_thread(
            build_bisection_ising, nodes, target_fraction, payload.balance_weight
        )
        build_ms = _ms(t0)

        t0 = time.perf_counter()
        energies, classical_best, optimal_energy = await asyncio.to_thread(
            _exact_classical, problem
        )
        classical_ms = _ms(t0)

        def outcome_for(index: int) -> _StepOutcome:
            ids = set()
            for q, node in enumerate(problem.nodes):
                if not (index >> q) & 1:  # bit 0 -> z=+1 -> side A
                    ids.update(node.point_ids)
            return _StepOutcome(ids)

        if provider is None or problem.num_qubits < 2:
            return outcome_for(classical_best)

        n, reps, shots = problem.num_qubits, payload.qaoa_reps, payload.shots
        circuit_stats = logical_circuit_stats(problem, reps)
        optimal_mask = np.abs(energies - optimal_energy) < ENERGY_TOLERANCE
        run = await self.run_repository.create(
            territory_plan_id=plan_id,
            step=step,
            provider=provider.name,
            status="submitted",
            num_qubits=n,
            num_terms=problem.num_terms,
            qaoa_reps=reps,
            shots=shots,
            logical_depth=circuit_stats["logical_depth"],
            two_qubit_gates=circuit_stats["rzz_gates"],
            build_ms=build_ms,
            classical_ms=classical_ms,
            optimal_energy=optimal_energy,
            details={
                "circuit": circuit_stats,
                "target_fraction": target_fraction,
                "balance_weight": payload.balance_weight,
                "energy_scale": problem.scale,
                "micro_zones": [len(z.point_ids) for z in problem.nodes],
                "graph_edges": len(problem.edges),
                "optimal_solutions": int(optimal_mask.sum()),
                "uniform_optimum_probability": float(optimal_mask.mean()),
                "classical_best_bitstring": format(classical_best, f"0{n}b"),
            },
        )

        async def finish(status: str, error: str | None = None, **fields) -> _StepOutcome:
            fields.setdefault("chosen_source", "classical")
            await self.run_repository.update(
                run.id,
                status=status,
                error=error,
                total_ms=_ms(step_started),
                completed_at=datetime.now(UTC),
                **fields,
            )
            return outcome_for(classical_best)

        if provider.name == "ibm_quantum":
            month_start = datetime.now(UTC).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            used = await self.run_repository.qpu_seconds_since(month_start, "ibm_quantum")
            if used >= self.settings.IBM_QUANTUM_MONTHLY_BUDGET_SECONDS:
                return await finish(
                    "budget_exceeded",
                    f"Monthly QPU budget used: {used:.1f}s of "
                    f"{self.settings.IBM_QUANTUM_MONTHLY_BUDGET_SECONDS:.0f}s",
                )

        ledger_id = None
        try:
            # Variational loop on the exact simulator (free); only the final
            # sampling goes to the selected backend ("parameter transfer").
            t0 = time.perf_counter()
            params = await asyncio.to_thread(optimize_parameters, energies, n, reps)
            optimize_ms = _ms(t0)
            ideal_probs = await asyncio.to_thread(
                probabilities, energies, n, params.gammas, params.betas
            )

            # Qiskit-backed providers must stay on the single Qiskit thread (see
            # quantum_ledger.runtime); the NumPy simulator can use any thread.
            on_worker = run_qiskit if provider.uses_qiskit else asyncio.to_thread
            prepared = await on_worker(provider.prepare, problem, params, shots)
            if self.ledger is not None and prepared.logical_circuit is not None:
                # Recorded BEFORE submit: if anything below dies, we still
                # know exactly what was (about to be) sent.
                ledger_record = await self.ledger.open(
                    source="territory_plan",
                    source_id=str(plan_id),
                    source_step=step,
                    provider=provider.name,
                    is_real_hardware=provider.name == "ibm_quantum",
                    backend=prepared.backend,
                    logical_circuit=prepared.logical_circuit,
                    isa_circuit=prepared.circuit,
                    shots=shots,
                    parameters={
                        "algorithm": "QAOA",
                        "reps": reps,
                        "gammas": params.gammas,
                        "betas": params.betas,
                        "angles_optimized_on": "numpy statevector (parameter transfer)",
                        "optimizer_evaluations": params.evaluations,
                        "target_fraction": target_fraction,
                        "balance_weight": payload.balance_weight,
                    },
                    run_options={"primitive": "SamplerV2", "optimization_level": 1},
                    problem=ising_problem_from_arrays(problem.J, problem.h, problem.const),
                    classical_reference={
                        "method": "exhaustive_search",
                        "search_space": 2**n,
                        "optimal_cost": optimal_energy,
                        "optimal_bitstrings": [
                            format(int(i), f"0{n}b") for i in np.flatnonzero(optimal_mask)
                        ],
                        "solve_ms": classical_ms,
                    },
                    transpile_ms=prepared.transpile_ms,
                    channel=self.settings.IBM_QUANTUM_CHANNEL
                    if provider.name == "ibm_quantum"
                    else None,
                    instance=(self.settings.IBM_QUANTUM_INSTANCE or None)
                    if provider.name == "ibm_quantum"
                    else None,
                )
                ledger_id = ledger_record.id
                await self.run_repository.update(
                    run.id, details={**run.details, "ledger_id": str(ledger_id)}
                )
            submission = await on_worker(provider.submit, prepared)
            if ledger_id is not None:
                await self.ledger.mark_submitted(ledger_id, submission.job_id)
            await self.run_repository.update(
                run.id,
                job_id=submission.job_id,
                backend_name=prepared.backend_name,
                submitted_at=submission.submitted_at,
                optimize_ms=optimize_ms,
                optimizer_evaluations=params.evaluations,
                transpile_ms=prepared.transpile_ms,
                transpiled_depth=prepared.transpiled_depth,
                transpiled_two_qubit_gates=prepared.transpiled_two_qubit_gates,
            )
            wait_started = time.perf_counter()
            if provider.uses_qiskit:
                # queue time is spent polling here, not blocking the Qiskit thread
                try:
                    await wait_until_done(
                        submission.handle, self.settings.IBM_QUANTUM_TIMEOUT_SECONDS
                    )
                except TimeoutError as exc:
                    raise QuantumTimeoutError(str(exc)) from exc
            result = await on_worker(
                provider.wait, submission, self.settings.IBM_QUANTUM_TIMEOUT_SECONDS
            )
            if provider.uses_qiskit:
                # submit -> result as we experienced it (queue + run + decode);
                # the local emulator has no device timestamps, so this is its run time
                waited_ms = _ms(wait_started)
                result.details["wait_wall_ms"] = waited_ms
                if result.raw is not None and result.raw.execution_ms is None:
                    result.execution_ms = waited_ms
        except QuantumTimeoutError as exc:
            message = f"No result within {self.settings.IBM_QUANTUM_TIMEOUT_SECONDS}s: {exc}"
            if ledger_id is not None:
                # the job keeps running at IBM — POST /quantum/ledger/{id}/sync recovers it
                await self.ledger.mark_timeout(ledger_id, message)
            return await finish("timeout", message)
        except Exception as exc:  # any backend failure degrades to the classical answer
            message = f"{type(exc).__name__}: {exc}"
            if ledger_id is not None:
                await self.ledger.fail(ledger_id, message)
            return await finish("failed", message)

        if ledger_id is not None and result.raw is not None:
            noisy_counts = noisy_ms = None
            if (
                provider.name == "ibm_quantum"
                and self.settings.QUANTUM_LEDGER_NOISE_MODEL_PREDICTION
            ):
                try:
                    noisy_counts, noisy_ms = await run_qiskit(
                        noise_model_counts, prepared.circuit, prepared.backend, shots
                    )
                except Exception:  # a prediction is a bonus, never a failure
                    noisy_counts = noisy_ms = None
            await self.ledger.complete(
                ledger_id,
                result.raw,
                wait_wall_ms=result.details.get("wait_wall_ms"),
                noisy_counts=noisy_counts,
                noisy_ms=noisy_ms,
            )

        total_shots = sum(result.counts.values()) or 1
        best_sampled = min(result.counts, key=lambda idx: energies[idx])
        best_energy = float(energies[best_sampled])
        expected_sampled = float(
            sum(energies[i] * c for i, c in result.counts.items()) / total_shots
        )
        sampled_opt = sum(c for i, c in result.counts.items() if optimal_mask[i]) / total_shots
        quantum_ok = best_energy <= optimal_energy + ENERGY_TOLERANCE

        run = await self.run_repository.get(run.id)
        details = dict(run.details)
        details.update(
            {
                "gammas": params.gammas,
                "betas": params.betas,
                "ideal_expected_energy": params.expected_energy,
                "ideal_optimum_probability": float(ideal_probs[optimal_mask].sum()),
                "top_counts": top_counts(result.counts, energies, n),
                "best_sampled_bitstring": format(best_sampled, f"0{n}b"),
                "prepare": prepared.details,
                "execution": result.details,
            }
        )
        await self.run_repository.update(
            run.id,
            status="completed",
            queue_ms=result.queue_ms,
            execution_ms=result.execution_ms,
            qpu_seconds=result.qpu_seconds,
            expected_energy=expected_sampled,
            best_energy=best_energy,
            approximation_ratio=_approximation_ratio(expected_sampled, energies),
            optimum_probability=float(ideal_probs[optimal_mask].sum()),
            sampled_optimum_frequency=float(sampled_opt),
            unique_bitstrings=len(result.counts),
            chosen_source="quantum" if quantum_ok else "classical",
            details=details,
            total_ms=_ms(step_started),
            completed_at=result.completed_at,
        )
        return outcome_for(best_sampled if quantum_ok else classical_best)

    @staticmethod
    def _summarize(points: list[Point], assignment: dict[str, int], vehicles) -> tuple[list, dict]:
        zones = []
        for index, vehicle in enumerate(vehicles):
            members = [p for p in points if assignment.get(p.id) == index]
            if members:
                lat = float(np.mean([p.latitude for p in members]))
                lng = float(np.mean([p.longitude for p in members]))
                radius = max(
                    math.dist(
                        (p.latitude * 110.57, p.longitude * 111.32 * math.cos(math.radians(lat))),
                        (lat * 110.57, lng * 111.32 * math.cos(math.radians(lat))),
                    )
                    for p in members
                )
            else:
                lat = lng = None
                radius = 0.0
            zones.append(
                {
                    "index": index,
                    "vehicle_id": str(vehicle.id),
                    "plate_number": vehicle.plate_number,
                    "delivery_ids": [p.id for p in members],
                    "stop_count": len(members),
                    "load": float(sum(p.load for p in members)),
                    "centroid_lat": lat,
                    "centroid_lng": lng,
                    "radius_km": round(radius, 3),
                }
            )
        loads = [z["load"] for z in zones]
        mean_load = (sum(loads) / len(loads)) if loads else 0.0
        metrics = {
            "max_load": max(loads, default=0.0),
            "min_load": min(loads, default=0.0),
            # 1.0 = perfectly balanced; 1.5 = busiest zone has 50% more than average
            "imbalance": (max(loads) / mean_load) if mean_load else 0.0,
            "max_radius_km": max((z["radius_km"] for z in zones), default=0.0),
        }
        return zones, metrics
