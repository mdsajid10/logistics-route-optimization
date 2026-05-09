from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.algorithms.aco import run_aco
from backend.algorithms.ga import run_ga
from backend.algorithms.hybrid import run_hybrid_ga_aco
from backend.utils.csv_parser import parse_csv_bytes
from backend.utils.distance import (
    build_distance_matrix,
    route_distance,
    route_to_geojson_like,
    route_to_road_points,
)


class AppState:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.coords: list[tuple[float, float]] = []
        self.distance_matrix: np.ndarray | None = None
        self.distance_details: dict[str, Any] = {}
        self.baseline_distance: float | None = None
        self.results: dict[str, Any] | None = None


state = AppState()

app = FastAPI(title="Logistics Route Optimization & Comparison System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        content = await file.read()
        parsed = parse_csv_bytes(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    nodes = parsed["nodes"]
    coords = [(n["latitude"], n["longitude"]) for n in nodes]

    matrix, details = build_distance_matrix(coords, return_details=True)

    baseline_route = list(range(len(nodes)))
    baseline_distance = route_distance(
        baseline_route,
        matrix,
        return_to_start=True,
    )

    state.nodes = nodes
    state.coords = coords
    state.distance_matrix = matrix
    state.distance_details = details
    state.baseline_distance = baseline_distance
    state.results = None

    return {
        "message": "CSV uploaded successfully",
        "node_count": len(nodes),
        "preview": nodes[:5],
    }


def _format_algorithm_output(
    name: str,
    route: list[int],
    metrics: dict[str, Any],
) -> dict[str, Any]:

    efficiency = 0.0

    if state.baseline_distance and metrics["distance_km"] > 0:
        efficiency = (
            state.baseline_distance / metrics["distance_km"]
        ) * 100.0

    requested_mode = str(
        state.distance_details.get("requested_mode", "haversine")
    )

    if requested_mode.startswith("road_"):
        route_points = route_to_road_points(
            route,
            state.coords,
            mode=requested_mode,
        )
    else:
        route_points = route_to_geojson_like(route, state.coords)

    route_stops = []

    for seq, idx in enumerate(route, start=1):
        node = state.nodes[idx]

        route_stops.append(
            {
                "sequence": seq,
                "node_id": int(node.get("node_id", idx)),
                "order_id": str(node.get("order_id", f"ORD-{idx + 1}")),
                "latitude": float(node["latitude"]),
                "longitude": float(node["longitude"]),
            }
        )

    return {
        "algorithm": name,
        "route_indices": route,
        "route_points": route_points,
        "route_stops": route_stops,
        "distance_km": round(float(metrics["distance_km"]), 4),
        "eta_hours": round(float(metrics["eta_hours"]), 4),
        "fuel_cost": round(float(metrics["fuel_cost"]), 4),
        "objective": round(float(metrics["objective"]), 4),
        "route_efficiency_pct": round(float(efficiency), 2),
    }


@app.get("/run-algorithms")
def run_algorithms() -> dict[str, Any]:

    if state.distance_matrix is None or not state.nodes:
        raise HTTPException(
            status_code=400,
            detail="Upload CSV first.",
        )

    node_count = len(state.nodes)

    ga = run_ga(state.distance_matrix, node_count)
    aco = run_aco(state.distance_matrix, node_count)
    hybrid = run_hybrid_ga_aco(state.distance_matrix, node_count)

    ga_out = _format_algorithm_output(
        "GA",
        ga["route"],
        ga["metrics"],
    )

    aco_out = _format_algorithm_output(
        "ACO",
        aco["route"],
        aco["metrics"],
    )

    hy_out = _format_algorithm_output(
        "Hybrid GA-ACO",
        hybrid["route"],
        hybrid["metrics"],
    )

    all_results = [ga_out, aco_out, hy_out]

    best_distance = min(
        all_results,
        key=lambda x: x["distance_km"],
    )

    best_cost = min(
        all_results,
        key=lambda x: x["objective"],
    )

    state.results = {
        "node_count": node_count,
        "baseline_distance_km": round(
            float(state.baseline_distance or 0.0),
            3,
        ),
        "distance_mode_requested": state.distance_details.get(
            "requested_mode",
            "haversine",
        ),
        "distance_mode_effective": state.distance_details.get(
            "effective_mode",
            "haversine",
        ),
        "distance_provider": state.distance_details.get(
            "provider",
            "haversine",
        ),
        "distance_fallback_used": bool(
            state.distance_details.get(
                "fallback_used",
                False,
            )
        ),
        "results": all_results,
        "best_by_distance": best_distance["algorithm"],
        "best_by_cost": best_cost["algorithm"],
    }

    return state.results


@app.get("/results")
def get_results() -> dict[str, Any]:

    if state.results is None:
        raise HTTPException(
            status_code=404,
            detail="No results found. Run /run-algorithms first.",
        )

    return state.results


frontend_dir = Path(__file__).resolve().parents[1] / "frontend"

if frontend_dir.exists():
    app.mount(
        "/",
        StaticFiles(directory=frontend_dir, html=True),
        name="frontend",
    )