"""Quantum backends behind one interface: prepare → submit → wait.

The split mirrors how a real QPU behaves: `submit` returns a job id within
seconds, `wait` may block for minutes in IBM's queue. The service persists
the job id between the two calls, so a crash mid-wait never loses a paid job.

- NumpyStatevectorProvider ("quantum_simulator"): exact, noiseless, always
  available, no extra dependencies.
- IbmRuntimeProvider(emulator=True) ("ibm_emulator"): the real Qiskit
  transpile + SamplerV2 path against a local fake IBM device (real topology,
  gate set and noise model). Needs the optional `quantum` extra.
- IbmRuntimeProvider(emulator=False) ("ibm_quantum"): a real IBM QPU via
  qiskit-ibm-runtime. Needs the extra plus IBM_QUANTUM_TOKEN.

Qiskit is imported lazily so the API image works without it.
"""

import importlib.util
import time
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.quantum_ledger.ibm import wait_and_extract
from app.services.territory.problem import IsingProblem, ising_energies
from app.services.territory.qaoa import QaoaParameters, probabilities, sample

EMULATOR_BACKEND = "FakeBrisbane"


@dataclass
class PreparedJob:
    circuit: Any
    shots: int
    backend_name: str
    transpile_ms: float | None = None
    transpiled_depth: int | None = None
    transpiled_two_qubit_gates: int | None = None
    details: dict = field(default_factory=dict)
    # IBM paths only: what the ledger records (the pre-transpile circuit and
    # the backend object, for its calibration data)
    logical_circuit: Any = None
    backend: Any = None


@dataclass
class Submission:
    job_id: str | None
    submitted_at: datetime
    handle: Any = None


@dataclass
class ExecutionResult:
    counts: dict[int, int]  # assignment index -> shots
    execution_ms: float | None
    queue_ms: float | None = None
    qpu_seconds: float | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict = field(default_factory=dict)
    # IBM paths only: the full extracted job result (per-shot memory, IBM
    # metadata) for the quantum ledger
    raw: Any = None


class QuantumTimeoutError(Exception):
    """The job didn't finish within the wait budget (it may still run later)."""


def qiskit_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None
        for name in ("qiskit", "qiskit_ibm_runtime", "qiskit_aer")
    )


class NumpyStatevectorProvider:
    name = "numpy_statevector"
    uses_qiskit = False

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def prepare(self, problem: IsingProblem, params: QaoaParameters, shots: int) -> PreparedJob:
        return PreparedJob(
            circuit=(problem, params),
            shots=shots,
            backend_name="statevector (exact)",
        )

    def submit(self, prepared: PreparedJob) -> Submission:
        started = time.perf_counter()
        problem, params = prepared.circuit
        probs = probabilities(
            ising_energies(problem), problem.num_qubits, params.gammas, params.betas
        )
        counts = sample(probs, prepared.shots, seed=self.seed)
        result = ExecutionResult(counts=counts, execution_ms=(time.perf_counter() - started) * 1000)
        return Submission(job_id=None, submitted_at=datetime.now(UTC), handle=result)

    def wait(self, submission: Submission, timeout_seconds: float) -> ExecutionResult:
        return submission.handle


def build_qaoa_circuit(problem: IsingProblem, params: QaoaParameters):
    """Qiskit circuit equal (up to global phase) to qaoa.statevector."""
    from qiskit import QuantumCircuit

    n = problem.num_qubits
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for gamma, beta in zip(params.gammas, params.betas):
        for i in range(n):
            for j in range(i + 1, n):
                if abs(problem.J[i, j]) > 1e-12:
                    qc.rzz(2 * gamma * problem.J[i, j], i, j)
        for i in range(n):
            if abs(problem.h[i]) > 1e-12:
                qc.rz(2 * gamma * problem.h[i], i)
        qc.rx(2 * beta, range(n))
    qc.measure_all()
    return qc


def _two_qubit_gate_count(circuit) -> int:
    return sum(1 for inst in circuit.data if inst.operation.num_qubits == 2)


class IbmRuntimeProvider:
    uses_qiskit = True

    def __init__(
        self,
        *,
        emulator: bool,
        token: str = "",
        instance: str = "",
        channel: str = "ibm_quantum_platform",
        backend_name: str = "",
    ) -> None:
        self.emulator = emulator
        self.name = "ibm_emulator" if emulator else "ibm_quantum"
        self.token = token
        self.instance = instance
        self.channel = channel
        self.backend_name = backend_name
        self._backend = None

    def _get_backend(self, num_qubits: int):
        if self._backend is not None:
            return self._backend
        if self.emulator:
            from qiskit_ibm_runtime import fake_provider

            self._backend = getattr(fake_provider, EMULATOR_BACKEND)()
        else:
            from qiskit_ibm_runtime import QiskitRuntimeService

            service = QiskitRuntimeService(
                channel=self.channel, token=self.token, instance=self.instance or None
            )
            self._backend = (
                service.backend(self.backend_name)
                if self.backend_name
                else service.least_busy(
                    operational=True, simulator=False, min_num_qubits=num_qubits
                )
            )
        return self._backend

    def prepare(self, problem: IsingProblem, params: QaoaParameters, shots: int) -> PreparedJob:
        from qiskit.transpiler import generate_preset_pass_manager

        backend = self._get_backend(problem.num_qubits)
        circuit = build_qaoa_circuit(problem, params)
        started = time.perf_counter()
        isa = generate_preset_pass_manager(optimization_level=1, backend=backend).run(circuit)
        transpile_ms = (time.perf_counter() - started) * 1000
        layout = isa.layout.final_index_layout() if isa.layout is not None else None
        return PreparedJob(
            circuit=isa,
            shots=shots,
            backend_name=backend.name,
            transpile_ms=transpile_ms,
            transpiled_depth=isa.depth(),
            transpiled_two_qubit_gates=_two_qubit_gate_count(isa),
            details={
                "physical_qubits": layout,
                "backend_num_qubits": backend.num_qubits,
                "gate_counts": {k: int(v) for k, v in isa.count_ops().items()},
                "logical_two_qubit_gates": _two_qubit_gate_count(circuit),
            },
            logical_circuit=circuit,
            backend=backend,
        )

    def submit(self, prepared: PreparedJob) -> Submission:
        with warnings.catch_warnings():
            # qiskit-ibm-runtime ≥0.45 deprecates SamplerV2 in favour of the
            # executor-based sampler; the PUB interface is identical.
            warnings.simplefilter("ignore", DeprecationWarning)
            from qiskit_ibm_runtime import SamplerV2

            sampler = SamplerV2(mode=self._backend)
            job = sampler.run([prepared.circuit], shots=prepared.shots)
        return Submission(job_id=str(job.job_id()), submitted_at=datetime.now(UTC), handle=job)

    def wait(self, submission: Submission, timeout_seconds: float) -> ExecutionResult:
        try:
            extracted, wall_ms = wait_and_extract(submission.handle, timeout_seconds)
        except TimeoutError as exc:
            raise QuantumTimeoutError(str(exc)) from exc

        details: dict = {"wait_wall_ms": wall_ms}
        if extracted.job_metrics:
            details["ibm_timestamps"] = extracted.job_metrics.get("timestamps")
            details["ibm_usage"] = extracted.job_metrics.get("usage")
            details["ibm_qiskit_version"] = extracted.job_metrics.get("qiskit_version")
        if self.emulator:
            # local fake-backend jobs report placeholder timestamps/usage
            extracted.queue_ms = extracted.execution_ms = extracted.qpu_seconds = None
        return ExecutionResult(
            counts={int(bits, 2): count for bits, count in extracted.counts.items()},
            # emulator: local wall time of the noisy simulation
            execution_ms=extracted.execution_ms if extracted.execution_ms is not None else wall_ms,
            queue_ms=extracted.queue_ms,
            qpu_seconds=extracted.qpu_seconds,
            details=details,
            raw=extracted,
        )


def top_counts(counts: dict[int, int], energies: np.ndarray, num_qubits: int, limit: int = 12):
    """Most frequent outcomes with their (normalized) cost — for the dashboard."""
    total = sum(counts.values()) or 1
    rows = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [
        {
            "bitstring": format(idx, f"0{num_qubits}b"),
            "count": count,
            "probability": count / total,
            "energy": float(energies[idx]),
        }
        for idx, count in rows
    ]
