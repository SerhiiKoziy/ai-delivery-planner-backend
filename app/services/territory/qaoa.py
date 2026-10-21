"""QAOA for a diagonal Ising cost, simulated exactly on a NumPy statevector.

    |ψ(γ, β)⟩ = Π_layers  e^{-iβ ΣX} · e^{-iγ H_C}  |+⟩^n

H_C is diagonal (its diagonal is `ising_energies`), so the cost layer is an
elementwise phase and each mixer RX(2β) is a 2x2 rotation on one axis of the
reshaped state — 2^n memory, fast up to the ~12–16 qubits we allow.

The same angles define the Qiskit circuit in `providers.build_qaoa_circuit`
(RZZ(2γJ), RZ(2γh), RX(2β)), so angles optimized here can be sent to real
hardware for sampling only ("parameter transfer"): the expensive variational
loop never spends QPU time.
"""

from dataclasses import dataclass

import numpy as np

from app.services.territory.problem import IsingProblem


@dataclass
class QaoaParameters:
    gammas: list[float]
    betas: list[float]
    expected_energy: float
    evaluations: int


def statevector(energies: np.ndarray, num_qubits: int, gammas, betas) -> np.ndarray:
    psi = np.full(2**num_qubits, 2 ** (-num_qubits / 2), dtype=complex)
    for gamma, beta in zip(gammas, betas):
        psi = psi * np.exp(-1j * gamma * energies)
        cos, sin = np.cos(beta), np.sin(beta)
        for q in range(num_qubits):
            view = psi.reshape(-1, 2, 2**q)
            zero, one = view[:, 0, :].copy(), view[:, 1, :].copy()
            view[:, 0, :] = cos * zero - 1j * sin * one
            view[:, 1, :] = -1j * sin * zero + cos * one
    return psi


def probabilities(energies: np.ndarray, num_qubits: int, gammas, betas) -> np.ndarray:
    probs = np.abs(statevector(energies, num_qubits, gammas, betas)) ** 2
    return probs / probs.sum()


def _nelder_mead(f, x0: np.ndarray, step: float = 0.15, max_evals: int = 300, tol: float = 1e-6):
    """Minimal Nelder–Mead (keeps scipy out of the runtime image)."""
    simplex = [x0] + [x0 + step * np.eye(len(x0))[i] for i in range(len(x0))]
    values = [f(x) for x in simplex]
    evals = len(simplex)
    while evals < max_evals:
        order = np.argsort(values)
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) < tol:
            break
        centroid = np.mean(simplex[:-1], axis=0)
        reflected = centroid + (centroid - simplex[-1])
        fr = f(reflected)
        evals += 1
        if values[0] <= fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
            continue
        if fr < values[0]:
            expanded = centroid + 2 * (reflected - centroid)
            fe = f(expanded)
            evals += 1
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
            continue
        contracted = centroid + 0.5 * (simplex[-1] - centroid)
        fc = f(contracted)
        evals += 1
        if fc < values[-1]:
            simplex[-1], values[-1] = contracted, fc
            continue
        simplex = [simplex[0]] + [simplex[0] + 0.5 * (x - simplex[0]) for x in simplex[1:]]
        values = [values[0]] + [f(x) for x in simplex[1:]]
        evals += len(simplex) - 1
    best = int(np.argmin(values))
    return simplex[best], values[best], evals


def optimize_parameters(energies: np.ndarray, num_qubits: int, reps: int) -> QaoaParameters:
    """Grid-search a p=1 start, ramp it to `reps` layers, refine with Nelder–Mead."""
    evals = 0

    def expectation(x: np.ndarray) -> float:
        nonlocal evals
        evals += 1
        probs = probabilities(energies, num_qubits, x[:reps], x[reps:])
        return float(probs @ energies)

    best_value, best_start = np.inf, (0.5, 0.4)
    for gamma in np.linspace(0.2, 2 * np.pi, 14):
        for beta in np.linspace(0.1, np.pi / 2, 8):
            evals += 1
            probs = probabilities(energies, num_qubits, [gamma], [beta])
            value = float(probs @ energies)
            if value < best_value:
                best_value, best_start = value, (gamma, beta)

    gamma0, beta0 = best_start
    # linear-ramp schedule (adiabatic-like): γ grows, β shrinks across layers
    ramp = np.linspace(0.5, 1.0, reps) if reps > 1 else np.array([1.0])
    x0 = np.concatenate([gamma0 * ramp, beta0 * ramp[::-1]])
    x, value, _ = _nelder_mead(expectation, x0)
    return QaoaParameters(
        gammas=[float(v) for v in x[:reps]],
        betas=[float(v) for v in x[reps:]],
        expected_energy=float(value),
        evaluations=evals,
    )


def sample(probs: np.ndarray, shots: int, seed: int = 0) -> dict[int, int]:
    """Draw `shots` assignment indices; returns {index: count}."""
    rng = np.random.default_rng(seed)
    draws = rng.choice(len(probs), size=shots, p=probs)
    values, counts = np.unique(draws, return_counts=True)
    return {int(v): int(c) for v, c in zip(values, counts)}


def logical_circuit_stats(problem: IsingProblem, reps: int) -> dict:
    """Gate counts/depth of the abstract (pre-transpile) QAOA circuit.

    Depth assumes all-to-all connectivity: RZZ gates on disjoint qubit pairs
    run in parallel, so one cost layer is as deep as a greedy edge colouring
    of the interaction graph. Real hardware adds SWAPs on top of this.
    """
    n = problem.num_qubits
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if abs(problem.J[i, j]) > 1e-12]
    colors: list[set[int]] = []
    for i, j in pairs:
        for used in colors:
            if i not in used and j not in used:
                used.update((i, j))
                break
        else:
            colors.append({i, j})
    has_rz = bool(np.any(np.abs(problem.h) > 1e-12))
    layer_depth = len(colors) + (1 if has_rz else 0) + 1  # RZZ colours + RZ + RX
    return {
        "rzz_gates": len(pairs) * reps,
        "rz_gates": int((np.abs(problem.h) > 1e-12).sum()) * reps,
        "rx_gates": n * reps,
        # each RZZ = 2 CNOTs + 1 RZ on hardware without a native ZZ gate
        "cnot_equivalent": 2 * len(pairs) * reps,
        "logical_depth": 1 + reps * layer_depth + 1,  # H layer, QAOA layers, measure
    }
