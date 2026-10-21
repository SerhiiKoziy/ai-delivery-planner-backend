"""Territory bisection as a QUBO / Ising problem.

One recursive-bisection step splits a set of delivery points into side A
(spin z=+1) and side B (z=-1) so that:

- few strong "affinity" edges are cut (nearby points stay in one zone), and
- side A carries ~`target_fraction` of the total load (zones are balanced).

    C(z) = Σ_edges w_ij (1 - z_i z_j) / 2  +  c · (Σ_i l_i z_i - t)²

Expanding the square gives an Ising Hamiltonian  const + Σ h_i z_i +
Σ_{i<j} J_ij z_i z_j, which is exactly what QAOA consumes. Note the balance
term couples EVERY pair of nodes (dense J) — that's the price of balance on
sparse-connectivity hardware, and why node count is capped.

Points are first aggregated into at most `max_nodes` micro-zones (k-means on
a local km projection), so the qubit count per step is bounded no matter
how many deliveries there are.
"""

from dataclasses import dataclass, field

import numpy as np

KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LNG_EQUATOR = 111.32


@dataclass
class Point:
    id: str  # Delivery UUID as a string
    latitude: float
    longitude: float
    load: float  # what zones are balanced by (1 per stop, or weight in kg)


@dataclass
class MicroZone:
    point_ids: list[str]
    load: float
    x_km: float
    y_km: float


@dataclass
class IsingProblem:
    """Ising form of one bisection step, already normalized (energy range ~[0, 1])."""

    nodes: list[MicroZone]
    J: np.ndarray  # (n, n) symmetric, zero diagonal; term is J_ij z_i z_j for i<j
    h: np.ndarray  # (n,)
    const: float
    scale: float  # raw cost = normalized cost * scale
    edges: list[tuple[int, int, float]] = field(default_factory=list)

    @property
    def num_qubits(self) -> int:
        return len(self.nodes)

    @property
    def num_terms(self) -> int:
        """Non-zero ZZ + Z terms — the gates the cost layer needs."""
        upper = np.triu(np.abs(self.J) > 1e-12, k=1)
        return int(upper.sum() + (np.abs(self.h) > 1e-12).sum())


def project_km(points: list[Point]) -> np.ndarray:
    """Equirectangular projection to a local km plane — fine at city scale."""
    lat0 = np.radians(np.mean([p.latitude for p in points]))
    return np.array(
        [
            [p.longitude * KM_PER_DEG_LNG_EQUATOR * np.cos(lat0), p.latitude * KM_PER_DEG_LAT]
            for p in points
        ],
        dtype=float,
    )


def aggregate(points: list[Point], max_nodes: int, seed: int = 0) -> list[MicroZone]:
    """Group points into ≤ max_nodes micro-zones (one per point if few enough)."""
    xy = project_km(points)
    if len(points) <= max_nodes:
        return [
            MicroZone([p.id], p.load, float(xy[i, 0]), float(xy[i, 1]))
            for i, p in enumerate(points)
        ]

    rng = np.random.default_rng(seed)
    # k-means++ init: spread the seeds, so dense blocks don't get all centers
    centers = [xy[rng.integers(len(xy))]]
    for _ in range(1, max_nodes):
        d2 = np.min(((xy[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        if d2.sum() == 0:
            break
        centers.append(xy[rng.choice(len(xy), p=d2 / d2.sum())])
    centers = np.array(centers)
    for _ in range(25):
        labels = np.argmin(((xy[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        new_centers = np.array(
            [
                xy[labels == k].mean(0) if np.any(labels == k) else centers[k]
                for k in range(len(centers))
            ]
        )
        if np.allclose(new_centers, centers):
            break
        centers = new_centers

    zones = []
    for k in range(len(centers)):
        members = [p for p, label in zip(points, labels) if label == k]
        if not members:
            continue
        zones.append(
            MicroZone(
                [p.id for p in members],
                float(sum(p.load for p in members)),
                float(centers[k, 0]),
                float(centers[k, 1]),
            )
        )
    return zones


def affinity_edges(nodes: list[MicroZone], k_neighbors: int = 3) -> list[tuple[int, int, float]]:
    """Sparse k-nearest-neighbour graph; w = √(l_i·l_j) · exp(-d / s).

    s is the median neighbour distance, so the weights are scale-free (a
    dense city center and a sparse suburb produce comparable graphs).
    """
    n = len(nodes)
    if n < 2:
        return []
    xy = np.array([[z.x_km, z.y_km] for z in nodes])
    dist = np.sqrt(((xy[:, None, :] - xy[None]) ** 2).sum(-1))
    k = min(k_neighbors, n - 1)
    neighbor_idx = np.argsort(dist, axis=1)[:, 1 : k + 1]
    pairs = {tuple(sorted((i, int(j)))) for i in range(n) for j in neighbor_idx[i]}
    scale = float(np.median([dist[i, j] for i, j in pairs])) or 1.0
    return [
        (i, j, float(np.sqrt(nodes[i].load * nodes[j].load) * np.exp(-dist[i, j] / scale)))
        for i, j in sorted(pairs)
    ]


def build_bisection_ising(
    nodes: list[MicroZone], target_fraction: float, balance_weight: float = 4.0
) -> IsingProblem:
    """Ising for "cut few edges, give side A `target_fraction` of the load"."""
    n = len(nodes)
    edges = affinity_edges(nodes)
    loads = np.array([z.load for z in nodes], dtype=float)
    total_load = float(loads.sum()) or 1.0
    total_weight = sum(w for _, _, w in edges) or 1.0

    J = np.zeros((n, n))
    h = np.zeros(n)
    const = 0.0
    for i, j, w in edges:  # w (1 - z_i z_j) / 2
        const += w / 2
        J[i, j] -= w / 2
        J[j, i] -= w / 2

    # c (Σ l_i z_i - t)², side A load = (L + Σ l_i z_i) / 2 = target_fraction · L
    t = total_load * (2 * target_fraction - 1)
    c = balance_weight * total_weight / total_load**2
    outer = 2 * c * np.outer(loads, loads)
    np.fill_diagonal(outer, 0.0)
    J += outer  # stored symmetric: the coefficient of z_i z_j (i<j) is J[i, j]
    h += -2 * c * t * loads
    const += c * (float((loads**2).sum()) + t**2)

    problem = IsingProblem(nodes=nodes, J=J, h=h, const=const, scale=1.0, edges=edges)
    energies = ising_energies(problem)
    scale = float(energies.max() - energies.min()) or 1.0
    return IsingProblem(
        nodes=nodes, J=J / scale, h=h / scale, const=const / scale, scale=scale, edges=edges
    )


def spins(num_qubits: int) -> np.ndarray:
    """(2^n, n) matrix of z values; row index bit q = qubit q, bit 0 -> z=+1 (side A).

    Same convention as Qiskit: integer index == int(bitstring, 2) with qubit
    0 as the rightmost character.
    """
    idx = np.arange(2**num_qubits)[:, None]
    bits = (idx >> np.arange(num_qubits)[None]) & 1
    return 1 - 2 * bits.astype(np.int8)


def ising_energies(problem: IsingProblem) -> np.ndarray:
    """Cost of every one of the 2^n assignments (the diagonal of H_C)."""
    z = spins(problem.num_qubits).astype(float)
    upper = np.triu(problem.J, k=1)
    return problem.const + z @ problem.h + np.einsum("si,ij,sj->s", z, upper, z)


def bits_to_sides(index: int, num_qubits: int) -> list[int]:
    """Assignment index -> [+1 / -1] per node (+1 = side A)."""
    return [1 - 2 * ((index >> q) & 1) for q in range(num_qubits)]


def bitstring(index: int, num_qubits: int) -> str:
    """Qiskit-style bitstring for an assignment index (qubit 0 rightmost)."""
    return format(index, f"0{num_qubits}b")
