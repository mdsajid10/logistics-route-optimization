from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from backend.utils.distance import summarize_route


@dataclass
class ACOConfig:
    ants: int = 25
    iterations: int = 60
    alpha_pheromone: float = 1.0
    beta_heuristic: float = 2.5
    evaporation: float = 0.50
    q: float = 80.0
    average_speed_kmph: float = 35.0
    fuel_rate_per_km: float = 0.22
    alpha: float = 1.0
    beta: float = 1.0
    seed: int | None = 55


def _route_edges(route: Sequence[int]) -> List[tuple[int, int]]:
    edges = [(route[i], route[i + 1]) for i in range(len(route) - 1)]
    edges.append((route[-1], route[0]))
    return edges


def _select_next(
    current: int,
    unvisited: list[int],
    pheromone: np.ndarray,
    heuristic: np.ndarray,
    cfg: ACOConfig,
    rng: np.random.Generator,
) -> int:
    desirability = []
    for nxt in unvisited:
        tau = pheromone[current, nxt] ** cfg.alpha_pheromone
        eta = heuristic[current, nxt] ** cfg.beta_heuristic
        desirability.append(tau * eta)

    probs = np.array(desirability, dtype=np.float64)
    probs_sum = probs.sum()

    if probs_sum <= 0:
        return int(rng.choice(unvisited))

    probs /= probs_sum
    return int(rng.choice(unvisited, p=probs))


def run_aco(
    distance_matrix: np.ndarray,
    node_count: int,
    cfg: ACOConfig | None = None,
    initial_routes: list[list[int]] | None = None,
) -> dict:
    cfg = cfg or ACOConfig()

    cfg.ants = min(max(15, node_count), cfg.ants)
    cfg.iterations = min(max(50, node_count * 2), cfg.iterations)

    rng = np.random.default_rng(cfg.seed)

    pheromone = np.ones((node_count, node_count), dtype=np.float64)
    np.fill_diagonal(pheromone, 0.0)

    # Inject useful GA edges to kick-start exploitation in hybrid mode.
    if initial_routes:
        for route in initial_routes:
            for i, j in _route_edges(route):
                pheromone[i, j] += 1.5
                pheromone[j, i] += 1.5

    heuristic = 1.0 / (distance_matrix + 1e-9)
    np.fill_diagonal(heuristic, 0.0)

    best_route = None
    best_objective = float("inf")

    for _ in range(cfg.iterations):
        ant_routes: list[list[int]] = []
        ant_objectives: list[float] = []

        for _ant in range(cfg.ants):
            route = [0]
            unvisited = list(range(1, node_count))

            while unvisited:
                current = route[-1]
                nxt = _select_next(current, unvisited, pheromone, heuristic, cfg, rng)
                route.append(nxt)
                unvisited.remove(nxt)

            metrics = summarize_route(
                route,
                distance_matrix,
                average_speed_kmph=cfg.average_speed_kmph,
                fuel_rate_per_km=cfg.fuel_rate_per_km,
                alpha=cfg.alpha,
                beta=cfg.beta,
            )
            objective = float(metrics["objective"])

            ant_routes.append(route)
            ant_objectives.append(objective)

            if objective < best_objective:
                best_objective = objective
                best_route = route[:]

        pheromone *= (1.0 - cfg.evaporation)

        for route, objective in zip(ant_routes, ant_objectives):
            deposit = cfg.q / (objective + 1e-6)
            for i, j in _route_edges(route):
                pheromone[i, j] += deposit
                pheromone[j, i] += deposit

        pheromone = np.clip(pheromone, 1e-6, 1e6)

    if best_route is None:
        best_route = list(range(node_count))

    metrics = summarize_route(
        best_route,
        distance_matrix,
        average_speed_kmph=cfg.average_speed_kmph,
        fuel_rate_per_km=cfg.fuel_rate_per_km,
        alpha=cfg.alpha,
        beta=cfg.beta,
    )

    return {
        "algorithm": "ACO",
        "route": best_route,
        "metrics": metrics,
    }
