"""Pure analysis helpers: compare what the device returned with what a CPU
computes. NumPy only; Qiskit is imported lazily inside the functions that
take circuits/backends.

Bitstring convention everywhere is Qiskit's: qubit 0 is the RIGHTMOST
character, so int(bitstring, 2) is the computational-basis index.
"""

import math
import time
from collections.abc import Iterable

import numpy as np

# Exact ideal distributions are 2^n — beyond this we don't store/compare them.
MAX_IDEAL_QUBITS = 16
COST_TOLERANCE = 1e-9


# ---------------------------------------------------------------- distributions
def normalize(counts: dict[str, int | float]) -> dict[str, float]:
    total = float(sum(counts.values()))
    return {k: v / total for k, v in counts.items()} if total else {}


def total_variation_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """½ Σ |p(x) - q(x)| — 0 = identical, 1 = disjoint."""
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def hellinger_fidelity(p: dict[str, float], q: dict[str, float]) -> float:
    """(Σ √(p·q))² — the same definition as qiskit.quantum_info.hellinger_fidelity."""
    overlap = sum(math.sqrt(p[k] * q[k]) for k in set(p) & set(q))
    return overlap**2


def entropy_bits(p: dict[str, float]) -> float:
    return -sum(v * math.log2(v) for v in p.values() if v > 0)


# ---------------------------------------------------------------- problem costs
def _spins(num_qubits: int) -> np.ndarray:
    idx = np.arange(2**num_qubits)[:, None]
    return 1 - 2 * ((idx >> np.arange(num_qubits)[None]) & 1)


def ising_costs(problem: dict) -> np.ndarray | None:
    """Cost of every basis state for {"kind": "ising", h, J: [[i, j, v]], const}.

    z_q = +1 for bit 0, -1 for bit 1:  C = const + Σ h_q z_q + Σ J_ij z_i z_j
    """
    if not problem or problem.get("kind") != "ising":
        return None
    n = int(problem["num_qubits"])
    if n > MAX_IDEAL_QUBITS:
        return None
    z = _spins(n).astype(float)
    costs = np.full(2**n, float(problem.get("const", 0.0)))
    costs += z @ np.asarray(problem.get("h", [0.0] * n), dtype=float)
    for i, j, v in problem.get("J", []):
        costs += v * z[:, int(i)] * z[:, int(j)]
    return costs


def ising_problem_from_arrays(J: np.ndarray, h: np.ndarray, const: float = 0.0) -> dict:
    """Serialize an Ising (J symmetric or upper-triangular, coefficient of
    z_i z_j for i<j is J[i, j]) into the ledger's JSON problem format."""
    n = len(h)
    return {
        "kind": "ising",
        "num_qubits": n,
        "h": [float(x) for x in h],
        "J": [
            [i, j, float(J[i, j])]
            for i in range(n)
            for j in range(i + 1, n)
            if abs(J[i, j]) > 1e-12
        ],
        "const": float(const),
    }


def _expected_cost(dist: dict[str, float], costs: np.ndarray) -> float:
    return float(sum(p * costs[int(b, 2)] for b, p in dist.items()))


# ---------------------------------------------------------------- the comparison
def compare(
    counts: dict[str, int],
    ideal: dict[str, float],
    problem: dict | None = None,
    noisy_model_counts: dict[str, int] | None = None,
) -> dict:
    """Everything we can say about a result vs. the CPU references.

    Pure function of stored columns, so it can be recomputed at any time
    (e.g. after a result is recovered by sync, or when metrics are added).
    """
    measured = normalize(counts)
    out: dict = {
        "shots": int(sum(counts.values())),
        "unique_outcomes": len(counts),
        "measured_entropy_bits": entropy_bits(measured),
    }
    if ideal:
        out.update(
            {
                "tvd_vs_ideal": total_variation_distance(measured, ideal),
                "hellinger_fidelity": hellinger_fidelity(measured, ideal),
                "ideal_entropy_bits": entropy_bits(ideal),
                "ideal_support": sum(1 for v in ideal.values() if v > 1e-9),
            }
        )
    if noisy_model_counts:
        model = normalize(noisy_model_counts)
        out["tvd_vs_noise_model"] = total_variation_distance(measured, model)
        out["noise_model_tvd_vs_ideal"] = total_variation_distance(model, ideal) if ideal else None

    costs = ising_costs(problem or {})
    if costs is not None and measured:
        best, worst = float(costs.min()), float(costs.max())
        span = (worst - best) or 1.0
        optimal = np.abs(costs - best) < COST_TOLERANCE
        optimal_bitstrings = {
            format(i, f"0{problem['num_qubits']}b") for i in np.flatnonzero(optimal)
        }
        uniform = float(optimal.mean())
        measured_opt = sum(p for b, p in measured.items() if b in optimal_bitstrings)
        best_measured = min(costs[int(b, 2)] for b in measured)
        out.update(
            {
                "optimal_cost": best,
                "worst_cost": worst,
                "optimal_bitstrings": sorted(optimal_bitstrings),
                "measured_expected_cost": _expected_cost(measured, costs),
                "best_measured_cost": float(best_measured),
                "found_optimum": bool(best_measured <= best + COST_TOLERANCE),
                "measured_optimum_frequency": measured_opt,
                "uniform_optimum_probability": uniform,
                "uniform_expected_cost": float(costs.mean()),
                "lift_over_random": measured_opt / uniform if uniform else None,
                # chance that the same number of uniformly random shots would
                # contain an optimum at least once
                "random_hit_probability": 1 - (1 - uniform) ** max(int(sum(counts.values())), 1),
            }
        )
        out["measured_approximation_ratio"] = (worst - out["measured_expected_cost"]) / span
        if ideal:
            out["ideal_expected_cost"] = _expected_cost(ideal, costs)
            out["ideal_approximation_ratio"] = (worst - out["ideal_expected_cost"]) / span
            out["ideal_optimum_probability"] = sum(
                p for b, p in ideal.items() if b in optimal_bitstrings
            )
    return out


def outcome_table(
    counts: dict[str, int], ideal: dict[str, float], problem: dict | None, limit: int = 64
) -> list[dict]:
    """Per-bitstring rows (measured vs ideal probability, cost) for charts:
    the union of the most frequent measured and the most likely ideal outcomes."""
    measured = normalize(counts)
    costs = ising_costs(problem or {})
    top = [b for b, _ in sorted(measured.items(), key=lambda kv: -kv[1])[:limit]]
    top += [b for b, _ in sorted(ideal.items(), key=lambda kv: -kv[1])[:limit]]
    rows = []
    for b in dict.fromkeys(top):
        rows.append(
            {
                "bitstring": b,
                "measured_probability": measured.get(b, 0.0),
                "measured_count": int(counts.get(b, 0)),
                "ideal_probability": ideal.get(b, 0.0),
                "cost": float(costs[int(b, 2)]) if costs is not None else None,
            }
        )
    return sorted(rows, key=lambda r: -(r["measured_probability"] + r["ideal_probability"]))


def per_qubit_marginals(
    counts: dict[str, int], ideal: dict[str, float], num_qubits: int
) -> list[dict]:
    """P(qubit q reads 1), measured vs ideal — readout bias shows up here first."""
    measured = normalize(counts)

    def p_one(dist: dict[str, float], q: int) -> float:
        return sum(p for b, p in dist.items() if b[-1 - q] == "1")

    return [
        {
            "qubit": q,
            "measured_p1": p_one(measured, q),
            "ideal_p1": p_one(ideal, q) if ideal else None,
        }
        for q in range(num_qubits)
    ]


def memory_drift(memory: list[str], problem: dict | None, windows: int = 8) -> list[dict]:
    """Shot sequence split into windows — does quality drift during the job?"""
    if not memory:
        return []
    costs = ising_costs(problem or {})
    size = max(1, math.ceil(len(memory) / windows))
    rows = []
    for start in range(0, len(memory), size):
        chunk = memory[start : start + size]
        row = {"from_shot": start, "to_shot": start + len(chunk) - 1, "unique": len(set(chunk))}
        if costs is not None:
            row["mean_cost"] = float(np.mean([costs[int(b, 2)] for b in chunk]))
        rows.append(row)
    return rows


# ---------------------------------------------------------------- circuits / CPU
def circuit_summary(circuit) -> dict:
    return {
        "depth": int(circuit.depth()),
        "ops": {k: int(v) for k, v in circuit.count_ops().items()},
        "two_qubit_gates": sum(1 for inst in circuit.data if inst.operation.num_qubits == 2),
        "num_qubits": int(circuit.num_qubits),
    }


def qasm2(circuit) -> str:
    from qiskit import qasm2 as _qasm2

    return _qasm2.dumps(circuit)


def ideal_distribution(circuit) -> tuple[dict[str, float], float]:
    """Exact noiseless output distribution (statevector) and CPU time in ms."""
    from qiskit.quantum_info import Statevector

    if circuit.num_qubits > MAX_IDEAL_QUBITS:
        return {}, 0.0
    started = time.perf_counter()
    bare = circuit.remove_final_measurements(inplace=False)
    probs = Statevector(bare).probabilities_dict()
    elapsed = (time.perf_counter() - started) * 1000
    return {k: float(v) for k, v in probs.items() if v > 1e-12}, elapsed


def noise_model_counts(
    isa_circuit, backend, shots: int, seed: int = 0
) -> tuple[dict[str, int], float]:
    """Run the transpiled circuit locally on Aer with `backend`'s noise model."""
    from qiskit_aer import AerSimulator

    started = time.perf_counter()
    sim = AerSimulator.from_backend(backend, seed_simulator=seed)
    counts = sim.run(isa_circuit, shots=shots).result().get_counts()
    return {k.replace(" ", ""): int(v) for k, v in counts.items()}, (
        time.perf_counter() - started
    ) * 1000


def _safe(fn, default=None):
    try:
        value = fn()
    except Exception:
        return default
    if value is None:
        return default
    return float(value) if isinstance(value, (int, float, np.floating)) else value


def calibration_snapshot(backend, physical_qubits: Iterable[int], isa_circuit=None) -> dict:
    """Device state for the qubits (and couplers) this job actually used."""
    target = getattr(backend, "target", None)
    qubits = sorted({int(q) for q in physical_qubits})
    snap: dict = {"qubits": [], "couplers": []}
    props = _safe(lambda: backend.properties())
    snap["calibrated_at"] = str(getattr(props, "last_update_date", "")) or None
    if target is None:
        return snap
    ops = set(target.operation_names)
    for q in qubits:
        qp = _safe(lambda: target.qubit_properties[q])
        row = {
            "physical": q,
            "t1_us": _safe(lambda: qp.t1 * 1e6) if qp is not None else None,
            "t2_us": _safe(lambda: qp.t2 * 1e6) if qp is not None else None,
            "frequency_ghz": _safe(lambda: qp.frequency / 1e9) if qp is not None else None,
        }
        for op in ("measure", "sx", "x"):
            if op in ops:
                row[f"{op}_error"] = _safe(lambda op=op: target[op][(q,)].error)
        row["readout_duration_us"] = (
            _safe(lambda: target["measure"][(q,)].duration * 1e6) if "measure" in ops else None
        )
        snap["qubits"].append(row)

    used_pairs: set[tuple[int, int]] = set()
    if isa_circuit is not None:
        for inst in isa_circuit.data:
            if inst.operation.num_qubits == 2:
                a, b = (isa_circuit.find_bit(x).index for x in inst.qubits)
                used_pairs.add((a, b))
    for op in ("ecr", "cz", "cx"):
        if op not in ops:
            continue
        for pair in sorted(used_pairs):
            if pair in target[op]:
                props_ = target[op][pair]
                snap["couplers"].append(
                    {
                        "gate": op,
                        "qubits": list(pair),
                        "error": _safe(lambda props_=props_: props_.error),
                        "duration_ns": _safe(lambda props_=props_: props_.duration * 1e9),
                    }
                )
    errs = [c["error"] for c in snap["couplers"] if c["error"] is not None]
    ro = [q["measure_error"] for q in snap["qubits"] if q.get("measure_error") is not None]
    snap["mean_two_qubit_error"] = float(np.mean(errs)) if errs else None
    snap["mean_readout_error"] = float(np.mean(ro)) if ro else None
    # crude "expected circuit fidelity" ≈ Π(1 - ε) over 2q gates and readouts
    if isa_circuit is not None and errs and ro:
        n2q = sum(1 for inst in isa_circuit.data if inst.operation.num_qubits == 2)
        snap["estimated_success_probability"] = float(
            (1 - np.mean(errs)) ** n2q * np.prod([1 - e for e in ro])
        )
    return snap
