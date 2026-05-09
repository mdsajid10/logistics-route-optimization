from __future__ import annotations

import numpy as np

from backend.algorithms.aco import ACOConfig, run_aco
from backend.algorithms.ga import GAConfig, run_ga
from backend.utils.distance import route_distance, summarize_route


def _two_opt_refine(route: list[int], distance_matrix: np.ndarray, max_passes: int = 20) -> list[int]:
    """Refine a route with 2-opt while keeping depot (index 0) fixed at start.
    
    Runs until no further improvement is found or max_passes is reached.
    """
    if len(route) < 4:
        return route[:]

    best = route[:]
    best_cost = route_distance(best, distance_matrix, return_to_start=True)

    for _ in range(max_passes):
        improved = False
        # Keep index 0 fixed; optimize only internal sequence.
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                cand_cost = route_distance(candidate, distance_matrix, return_to_start=True)
                if cand_cost + 1e-9 < best_cost:
                    best = candidate
                    best_cost = cand_cost
                    improved = True
        if not improved:
            break

    return best


def _or_opt_refine(route: list[int], distance_matrix: np.ndarray, max_passes: int = 10) -> list[int]:
    """Or-opt local search: try moving segments of 1, 2, or 3 consecutive nodes
    to a better position in the route. Depot (index 0) stays fixed."""
    if len(route) < 4:
        return route[:]

    best = route[:]
    best_cost = route_distance(best, distance_matrix, return_to_start=True)

    for _ in range(max_passes):
        improved = False
        for seg_len in (1, 2, 3):
            for i in range(1, len(best) - seg_len + 1):
                # Extract segment
                segment = best[i : i + seg_len]
                remaining = best[:i] + best[i + seg_len :]

                # Try inserting segment at every other position in remaining
                for j in range(1, len(remaining) + 1):
                    candidate = remaining[:j] + segment + remaining[j:]
                    cand_cost = route_distance(candidate, distance_matrix, return_to_start=True)
                    if cand_cost + 1e-9 < best_cost:
                        best = candidate
                        best_cost = cand_cost
                        improved = True
        if not improved:
            break

    return best


def _full_local_search(route: list[int], distance_matrix: np.ndarray) -> list[int]:
    """Apply alternating 2-opt and or-opt until convergence."""
    current = route[:]
    current_cost = route_distance(current, distance_matrix, return_to_start=True)

    for _ in range(5):  # max outer iterations
        refined = _two_opt_refine(current, distance_matrix, max_passes=20)
        refined = _or_opt_refine(refined, distance_matrix, max_passes=10)
        refined_cost = route_distance(refined, distance_matrix, return_to_start=True)

        if refined_cost + 1e-9 < current_cost:
            current = refined
            current_cost = refined_cost
        else:
            break

    return current


def _objective(route: list[int], distance_matrix: np.ndarray, aco_cfg: ACOConfig) -> float:
    metrics = summarize_route(
        route,
        distance_matrix,
        average_speed_kmph=aco_cfg.average_speed_kmph,
        fuel_rate_per_km=aco_cfg.fuel_rate_per_km,
        alpha=aco_cfg.alpha,
        beta=aco_cfg.beta,
    )
    return float(metrics["objective"])


def _nearest_neighbor_route(start: int, node_count: int, distance_matrix: np.ndarray) -> list[int]:
    """Build a route using nearest-neighbor greedy heuristic starting from `start`.
    
    Always returns a route starting with depot (node 0).
    """
    visited = {start}
    route = [start]
    current = start

    while len(route) < node_count:
        best_next = -1
        best_dist = float("inf")
        for j in range(node_count):
            if j not in visited and distance_matrix[current, j] < best_dist:
                best_dist = distance_matrix[current, j]
                best_next = j
        if best_next == -1:
            break
        route.append(best_next)
        visited.add(best_next)
        current = best_next

    # Rotate so depot (0) is first
    if 0 in route:
        idx = route.index(0)
        route = route[idx:] + route[:idx]

    return route


def _double_bridge_perturbation(route: list[int], rng: np.random.Generator) -> list[int]:
    """Apply a double-bridge perturbation (break route into 4 segments, reassemble).
    
    This is a standard technique for escaping 2-opt local optima in TSP.
    Keeps depot (index 0) fixed at position 0.
    """
    n = len(route)
    if n < 6:
        # Too small for meaningful perturbation; just do a random swap
        result = route[:]
        if n > 2:
            i, j = sorted(rng.choice(range(1, n), size=2, replace=False))
            result[i], result[j] = result[j], result[i]
        return result

    # Pick 3 random cut points in the interior (positions 1..n-1)
    cuts = sorted(rng.choice(range(1, n), size=3, replace=False))
    i, j, k = cuts

    # Split route into 4 segments: [0..i), [i..j), [j..k), [k..n)
    seg1 = route[:i]
    seg2 = route[i:j]
    seg3 = route[j:k]
    seg4 = route[k:]

    # Reassemble as: seg1 + seg3 + seg2 + seg4 (double-bridge reconnection)
    return seg1 + seg3 + seg2 + seg4


def run_hybrid_ga_aco(distance_matrix: np.ndarray, node_count: int) -> dict:
    """Run GA first for exploration, then seed ACO for intensified search.
    
    Uses multiple restarts with different seeds to escape local optima,
    followed by deep local search (2-opt + or-opt) on all candidate solutions.
    """

    # --- Phase 1: Multi-restart GA exploration ---
    ga_seeds = [42, 77, 123, 256, 501]
    all_elite_routes: list[list[int]] = []
    all_ga_best_routes: list[list[int]] = []

    for seed in ga_seeds:
        ga_cfg = GAConfig(
            population_size=120,
            generations=200,
            mutation_rate=0.20,
            elite_count=8,
            tournament_size=5,
            average_speed_kmph=35.0,
            fuel_rate_per_km=0.22,
            alpha=1.0,
            beta=1.0,
            seed=seed,
        )
        ga_result = run_ga(distance_matrix, node_count, ga_cfg)
        all_ga_best_routes.append(ga_result["route"])
        all_elite_routes.extend(ga_result.get("elite_routes", []))

    # Deduplicate elite routes (keep unique orderings)
    seen = set()
    unique_elites: list[list[int]] = []
    for route in all_elite_routes:
        key = tuple(route)
        if key not in seen:
            seen.add(key)
            unique_elites.append(route)

    # --- Phase 2: Multi-restart ACO intensification seeded by GA elites ---
    aco_seeds = [91, 137, 271]
    all_aco_best_routes: list[list[int]] = []

    for seed in aco_seeds:
        aco_cfg = ACOConfig(
            ants=60,
            iterations=200,
            evaporation=0.25,
            alpha_pheromone=1.2,
            beta_heuristic=3.5,
            q=100.0,
            average_speed_kmph=35.0,
            fuel_rate_per_km=0.22,
            alpha=1.0,
            beta=1.0,
            seed=seed,
        )
        aco_result = run_aco(
            distance_matrix,
            node_count,
            aco_cfg,
            initial_routes=unique_elites[:10],  # seed with top GA solutions
        )
        all_aco_best_routes.append(aco_result["route"])

    # --- Phase 3: Deep local search on all candidate solutions ---
    # Collect all candidates from both phases
    candidates: list[list[int]] = []
    candidates.extend(all_ga_best_routes)
    candidates.extend(all_aco_best_routes)
    candidates.extend(unique_elites[:10])

    # Add nearest-neighbor construction heuristic routes (unique to hybrid)
    for start_node in range(node_count):
        nn_route = _nearest_neighbor_route(start_node, node_count, distance_matrix)
        candidates.append(nn_route)

    # Deduplicate candidates
    seen_cands = set()
    unique_candidates: list[list[int]] = []
    for route in candidates:
        key = tuple(route)
        if key not in seen_cands:
            seen_cands.add(key)
            unique_candidates.append(route)

    # Apply full local search (2-opt + or-opt) to every candidate
    refined_candidates = [_full_local_search(route, distance_matrix) for route in unique_candidates]

    # Use objective function for final selection (accounts for distance, time, fuel)
    final_aco_cfg = ACOConfig(
        average_speed_kmph=35.0,
        fuel_rate_per_km=0.22,
        alpha=1.0,
        beta=1.0,
    )
    best_route = min(refined_candidates, key=lambda r: _objective(r, distance_matrix, final_aco_cfg))
    best_obj = _objective(best_route, distance_matrix, final_aco_cfg)

    # --- Phase 4: Iterated Local Search with double-bridge perturbation ---
    # This breaks out of local optima that simple 2-opt/or-opt cannot escape.
    rng = np.random.default_rng(314)
    ils_iterations = 30  # number of perturbation attempts

    for _ in range(ils_iterations):
        perturbed = _double_bridge_perturbation(best_route, rng)
        refined = _full_local_search(perturbed, distance_matrix)
        refined_obj = _objective(refined, distance_matrix, final_aco_cfg)
        if refined_obj + 1e-9 < best_obj:
            best_route = refined
            best_obj = refined_obj

    metrics = summarize_route(
        best_route,
        distance_matrix,
        average_speed_kmph=final_aco_cfg.average_speed_kmph,
        fuel_rate_per_km=final_aco_cfg.fuel_rate_per_km,
        alpha=final_aco_cfg.alpha,
        beta=final_aco_cfg.beta,
    )

    return {
        "algorithm": "Hybrid GA-ACO",
        "route": best_route,
        "metrics": metrics,
        "ga_seed_solution": all_ga_best_routes[0] if all_ga_best_routes else [],
        "aco_seed_solution": all_aco_best_routes[0] if all_aco_best_routes else [],
    }
