"""Unit tests for the territory QUBO/Ising model and the NumPy QAOA simulator."""

import itertools

import numpy as np
import pytest

from app.services.territory.problem import (
    Point,
    aggregate,
    build_bisection_ising,
    ising_energies,
    spins,
)
from app.services.territory.providers import NumpyStatevectorProvider, qiskit_available
from app.services.territory.qaoa import (
    logical_circuit_stats,
    optimize_parameters,
    probabilities,
    statevector,
)


def _two_clusters(n_per_cluster: int = 4) -> list[Point]:
    """Two tight groups ~5 km apart: the obvious balanced split keeps each group whole."""
    rng = np.random.default_rng(7)
    points = []
    for c, (lat, lng) in enumerate([(50.45, 30.45), (50.45, 30.52)]):
        for i in range(n_per_cluster):
            points.append(
                Point(f"{c}-{i}", lat + rng.normal(0, 0.002), lng + rng.normal(0, 0.002), 1.0)
            )
    return points


def _raw_cost(problem, z, balance_weight, target_fraction):
    loads = np.array([node.load for node in problem.nodes])
    total_load = loads.sum()
    total_weight = sum(w for _, _, w in problem.edges)
    cut = sum(w * (1 - z[i] * z[j]) / 2 for i, j, w in problem.edges)
    t = total_load * (2 * target_fraction - 1)
    return cut + balance_weight * total_weight / total_load**2 * (loads @ z - t) ** 2


@pytest.mark.parametrize("target_fraction", [0.5, 1 / 3])
def test_ising_energies_match_the_direct_cost_formula(target_fraction: float) -> None:
    problem = build_bisection_ising(aggregate(_two_clusters(), 12), target_fraction, 4.0)
    energies = ising_energies(problem)
    z = spins(problem.num_qubits)
    for index in [0, 1, 37, 2**problem.num_qubits - 1]:
        expected = _raw_cost(problem, z[index], 4.0, target_fraction)
        assert energies[index] * problem.scale == pytest.approx(expected)


def test_optimal_split_keeps_each_cluster_together() -> None:
    points = _two_clusters()
    problem = build_bisection_ising(aggregate(points, 12), 0.5, 4.0)
    best = int(np.argmin(ising_energies(problem)))
    side_a = {
        pid for q, node in enumerate(problem.nodes) if not (best >> q) & 1 for pid in node.point_ids
    }
    groups = {p.id[0] for p in points if p.id in side_a}
    assert len(side_a) == 4
    assert len(groups) == 1


def test_aggregation_caps_node_count_and_keeps_every_point() -> None:
    rng = np.random.default_rng(1)
    points = [
        Point(str(i), 50.4 + rng.random() * 0.1, 30.4 + rng.random() * 0.2, 1.0) for i in range(60)
    ]
    nodes = aggregate(points, 10)
    assert len(nodes) <= 10
    assert sorted(pid for node in nodes for pid in node.point_ids) == sorted(p.id for p in points)
    assert sum(node.load for node in nodes) == pytest.approx(60)


def test_qaoa_statevector_is_normalized_and_beats_uniform_guessing() -> None:
    problem = build_bisection_ising(aggregate(_two_clusters(), 12), 0.5, 4.0)
    energies = ising_energies(problem)
    n = problem.num_qubits
    params = optimize_parameters(energies, n, reps=2)

    psi = statevector(energies, n, params.gammas, params.betas)
    assert np.vdot(psi, psi).real == pytest.approx(1.0)

    probs = probabilities(energies, n, params.gammas, params.betas)
    optimal = np.isclose(energies, energies.min())
    assert params.expected_energy < energies.mean()
    assert probs[optimal].sum() > optimal.mean()


def test_logical_circuit_stats_count_dense_balance_couplings() -> None:
    problem = build_bisection_ising(aggregate(_two_clusters(), 12), 0.5, 4.0)
    stats = logical_circuit_stats(problem, reps=2)
    n = problem.num_qubits
    # the balance penalty couples every pair of nodes
    assert stats["rzz_gates"] == 2 * n * (n - 1) // 2
    assert stats["cnot_equivalent"] == 2 * stats["rzz_gates"]


def test_numpy_provider_samples_requested_number_of_shots() -> None:
    problem = build_bisection_ising(aggregate(_two_clusters(), 12), 0.5, 4.0)
    energies = ising_energies(problem)
    params = optimize_parameters(energies, problem.num_qubits, reps=1)
    provider = NumpyStatevectorProvider()
    submission = provider.submit(provider.prepare(problem, params, 1000))
    result = provider.wait(submission, timeout_seconds=1)
    assert sum(result.counts.values()) == 1000
    assert submission.job_id is None


@pytest.mark.skipif(not qiskit_available(), reason="quantum extra not installed")
def test_qiskit_circuit_reproduces_the_numpy_statevector() -> None:
    from qiskit.quantum_info import Statevector

    from app.services.territory.providers import build_qaoa_circuit

    problem = build_bisection_ising(aggregate(_two_clusters(3), 12), 0.5, 4.0)
    energies = ising_energies(problem)
    params = optimize_parameters(energies, problem.num_qubits, reps=2)
    circuit = build_qaoa_circuit(problem, params)
    circuit.remove_final_measurements()
    expected = probabilities(energies, problem.num_qubits, params.gammas, params.betas)
    assert np.allclose(Statevector(circuit).probabilities(), expected, atol=1e-9)


def test_spins_follow_qiskit_bit_order() -> None:
    z = spins(3)
    # index 1 = "001": qubit 0 is 1 -> side B (-1); qubits 1, 2 are 0 -> side A (+1)
    assert list(z[1]) == [-1, 1, 1]
    assert len({tuple(row) for row in z}) == 8
    assert all(set(row) <= {-1, 1} for row in itertools.islice(z, 8))
