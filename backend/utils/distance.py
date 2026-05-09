from __future__ import annotations

import json
import math
import os
from urllib import parse, request
from typing import Iterable, List, Sequence

import numpy as np

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance between two points in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _build_haversine_distance_matrix(coords: Sequence[tuple[float, float]]) -> np.ndarray:
    """Build a dense symmetric straight-line distance matrix for all coordinate pairs."""
    n = len(coords)
    matrix = np.zeros((n, n), dtype=np.float64)

    for i in range(n):
        lat1, lon1 = coords[i]
        for j in range(i + 1, n):
            lat2, lon2 = coords[j]
            d = haversine_km(lat1, lon1, lat2, lon2)
            matrix[i, j] = d
            matrix[j, i] = d

    return matrix


def _profile_from_mode(mode: str) -> str:
    if mode == "road_car":
        return "driving"
    if mode == "road_walk":
        return "walking"
    return "cycling"


def _fetch_osrm_json(url: str, timeout_sec: float = 15.0) -> dict:
    req = request.Request(url, headers={"User-Agent": "Capstone-Route-Optimizer/1.0"})
    with request.urlopen(req, timeout=timeout_sec) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _build_osrm_distance_matrix(coords: Sequence[tuple[float, float]], profile: str) -> np.ndarray:
    if len(coords) < 2:
        return np.zeros((len(coords), len(coords)), dtype=np.float64)

    # OSRM expects lon,lat pairs in the request path.
    coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
    base_url = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
    url = f"{base_url}/table/v1/{profile}/{coord_str}?annotations=distance"

    data = _fetch_osrm_json(url)
    distances = data.get("distances")
    if not isinstance(distances, list) or len(distances) != len(coords):
        raise ValueError("OSRM table API did not return a valid matrix.")

    matrix = np.array(distances, dtype=np.float64)
    # OSRM returns meters; convert to kilometers.
    matrix /= 1000.0
    return matrix


def build_distance_matrix(
    coords: Sequence[tuple[float, float]],
    return_details: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, str | bool]]:
    """
    Build distance matrix used by optimization.

    Modes (env `ROUTING_DISTANCE_MODE`):
    - road_bike (default): OSRM road-network distance with cycling profile
    - road_car: OSRM driving profile
    - road_walk: OSRM walking profile
    - haversine: straight-line fallback mode
    """
    mode = os.getenv("ROUTING_DISTANCE_MODE", "road_bike").strip().lower()
    if mode not in {"road_bike", "road_car", "road_walk", "haversine"}:
        mode = "road_bike"

    details: dict[str, str | bool] = {
        "requested_mode": mode,
        "effective_mode": mode,
        "provider": "haversine" if mode == "haversine" else "osrm",
        "fallback_used": False,
    }

    if mode == "haversine":
        matrix = _build_haversine_distance_matrix(coords)
        return (matrix, details) if return_details else matrix

    try:
        profile = _profile_from_mode(mode)
        matrix = _build_osrm_distance_matrix(coords, profile)
        return (matrix, details) if return_details else matrix
    except Exception:
        # Keep app usable even when road API is unavailable.
        details["effective_mode"] = "haversine"
        details["provider"] = "haversine"
        details["fallback_used"] = True
        matrix = _build_haversine_distance_matrix(coords)
        return (matrix, details) if return_details else matrix


def route_distance(route: Sequence[int], distance_matrix: np.ndarray, return_to_start: bool = True) -> float:
    """Compute total path distance for a route of node indices."""
    if not route:
        return 0.0

    total = 0.0
    for i in range(len(route) - 1):
        total += float(distance_matrix[route[i], route[i + 1]])

    if return_to_start and len(route) > 1:
        total += float(distance_matrix[route[-1], route[0]])

    return total


def route_to_geojson_like(route: Sequence[int], coords: Sequence[tuple[float, float]]) -> List[list[float]]:
    """Convert route indices into [lat, lon] points including return to start."""
    if not route:
        return []

    points = [[float(coords[idx][0]), float(coords[idx][1])] for idx in route]
    points.append([float(coords[route[0]][0]), float(coords[route[0]][1])])
    return points


def route_to_road_points(
    route: Sequence[int],
    coords: Sequence[tuple[float, float]],
    mode: str = "road_bike",
) -> List[list[float]]:
    """Build road-following [lat, lon] polyline for the route via OSRM route API."""
    if not route:
        return []

    if mode not in {"road_bike", "road_car", "road_walk"}:
        return route_to_geojson_like(route, coords)

    profile = _profile_from_mode(mode)
    route_cycle = list(route)
    if route_cycle[0] != route_cycle[-1]:
        route_cycle.append(route_cycle[0])

    coord_str = ";".join(f"{coords[idx][1]:.6f},{coords[idx][0]:.6f}" for idx in route_cycle)
    base_url = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
    query = parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    url = f"{base_url}/route/v1/{profile}/{coord_str}?{query}"

    try:
        data = _fetch_osrm_json(url)
        routes = data.get("routes")
        if not routes:
            raise ValueError("No route data")
        coordinates = routes[0].get("geometry", {}).get("coordinates", [])
        if not coordinates:
            raise ValueError("No geometry")
        return [[float(lat), float(lon)] for lon, lat in coordinates]
    except Exception:
        return route_to_geojson_like(route, coords)


def summarize_route(
    route: Sequence[int],
    distance_matrix: np.ndarray,
    average_speed_kmph: float,
    fuel_rate_per_km: float,
    alpha: float,
    beta: float,
    delay_factor: float = 1.0,
) -> dict:
    """Compute all route KPIs used for objective and dashboard comparison."""
    distance = route_distance(route, distance_matrix, return_to_start=True)
    eta_hours = (distance / max(average_speed_kmph, 1e-6)) * delay_factor
    fuel_cost = distance * fuel_rate_per_km
    objective = distance + alpha * eta_hours + beta * fuel_cost

    return {
        "distance_km": float(distance),
        "eta_hours": float(eta_hours),
        "fuel_cost": float(fuel_cost),
        "objective": float(objective),
    }
