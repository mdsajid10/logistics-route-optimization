from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from backend.utils.distance import summarize_route


@dataclass
class GAConfig:
    population_size: int = 50
    generations: int = 100
    mutation_rate: float = 0.12
    tournament_size: int = 3
    elite_count: int = 3
    average_speed_kmph: float = 35.0
    fuel_rate_per_km: float = 0.22
    alpha: float = 1.0
    beta: float = 1.0
    seed: int | None = 42


def _build_candidate(route_tail: np.ndarray) -> np.ndarray:
    return np.concatenate(([0], route_tail))


def _objective(candidate: np.ndarray, distance_matrix: np.ndarray, cfg: GAConfig) -> float:
    metrics = summarize_route(
        candidate.tolist(),
        distance_matrix,
        average_speed_kmph=cfg.average_speed_kmph,
        fuel_rate_per_km=cfg.fuel_rate_per_km,
        alpha=cfg.alpha,
        beta=cfg.beta,
    )
    return float(metrics["objective"])


def _tournament_select(pop: List[np.ndarray], scores: List[float], rng: np.random.Generator, k: int) -> np.ndarray:
    idxs = rng.choice(len(pop), size=min(k, len(pop)), replace=False)
    best_idx = min(idxs, key=lambda i: scores[i])
    return pop[int(best_idx)].copy()


def _order_crossover(parent_a: np.ndarray, parent_b: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = len(parent_a)
    if n < 2:
        return parent_a.copy(), parent_b.copy()

    i, j = sorted(rng.choice(n, size=2, replace=False))

    child1 = np.full(n, -1, dtype=np.int64)
    child2 = np.full(n, -1, dtype=np.int64)

    child1[i : j + 1] = parent_a[i : j + 1]
    child2[i : j + 1] = parent_b[i : j + 1]

    fill1 = [g for g in parent_b if g not in child1]
    fill2 = [g for g in parent_a if g not in child2]

    ptr = 0
    for idx in range(n):
        if child1[idx] == -1:
            child1[idx] = fill1[ptr]
            ptr += 1

    ptr = 0
    for idx in range(n):
        if child2[idx] == -1:
            child2[idx] = fill2[ptr]
            ptr += 1

    return child1, child2


def _swap_mutation(route_tail: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = len(route_tail)
    if n < 2:
        return route_tail

    i, j = rng.choice(n, size=2, replace=False)
    route_tail[i], route_tail[j] = route_tail[j], route_tail[i]
    return route_tail


def run_ga(distance_matrix: np.ndarray, node_count: int, cfg: GAConfig | None = None) -> dict:
    cfg = cfg or GAConfig()

    # Adapt defaults by problem size to stay fast for 20-100 nodes.
    cfg.population_size = min(max(30, node_count * 2), cfg.population_size)
    cfg.generations = min(max(60, node_count * 2), cfg.generations)

    rng = np.random.default_rng(cfg.seed)
    tail_nodes = np.arange(1, node_count, dtype=np.int64)

    population: List[np.ndarray] = [rng.permutation(tail_nodes) for _ in range(cfg.population_size)]

    best_score = float("inf")
    best_route = None

    for _ in range(cfg.generations):
        candidates = [_build_candidate(ind) for ind in population]
        scores = [_objective(route, distance_matrix, cfg) for route in candidates]

        rank = np.argsort(scores)
        elites = [population[i].copy() for i in rank[: cfg.elite_count]]

        if scores[int(rank[0])] < best_score:
            best_score = scores[int(rank[0])]
            best_route = candidates[int(rank[0])].copy()

        next_population: List[np.ndarray] = elites[:]

        while len(next_population) < cfg.population_size:
            p1 = _tournament_select(population, scores, rng, cfg.tournament_size)
            p2 = _tournament_select(population, scores, rng, cfg.tournament_size)

            c1, c2 = _order_crossover(p1, p2, rng)

            if rng.random() < cfg.mutation_rate:
                c1 = _swap_mutation(c1, rng)
            if rng.random() < cfg.mutation_rate:
                c2 = _swap_mutation(c2, rng)

            next_population.append(c1)
            if len(next_population) < cfg.population_size:
                next_population.append(c2)

        population = next_population

    if best_route is None:
        best_route = _build_candidate(population[0])

    metrics = summarize_route(
        best_route.tolist(),
        distance_matrix,
        average_speed_kmph=cfg.average_speed_kmph,
        fuel_rate_per_km=cfg.fuel_rate_per_km,
        alpha=cfg.alpha,
        beta=cfg.beta,
    )

    # Return top GA solutions so hybrid can exploit them.
    final_candidates = [_build_candidate(ind) for ind in population]
    final_scores = [_objective(route, distance_matrix, cfg) for route in final_candidates]
    top_idx = np.argsort(final_scores)[: max(3, cfg.elite_count)]
    elite_routes = [final_candidates[i].tolist() for i in top_idx]

    return {
        "algorithm": "GA",
        "route": best_route.tolist(),
        "metrics": metrics,
        "elite_routes": elite_routes,
    }
