"""
Test all 3 location datasets and verify Hybrid GA-ACO gives the best result.
"""
import os
import sys
import time

# Ensure we use haversine (no network dependency)
os.environ["ROUTING_DISTANCE_MODE"] = "haversine"

from backend.utils.csv_parser import parse_csv_bytes
from backend.utils.distance import build_distance_matrix
from backend.algorithms.ga import run_ga
from backend.algorithms.aco import run_aco
from backend.algorithms.hybrid import run_hybrid_ga_aco

CSV_FILES = [
    "test_locations.csv",   # Location 1: Delhi
    "location2.csv",        # Location 2: Mumbai
    "location3.csv",        # Location 3: Bangalore
]


def test_location(csv_path: str):
    print(f"\n{'=' * 70}")
    print(f"  Testing: {csv_path}")
    print(f"{'=' * 70}")

    with open(csv_path, "rb") as f:
        data = parse_csv_bytes(f.read())

    nodes = data["nodes"]
    coords = [(n["latitude"], n["longitude"]) for n in nodes]
    matrix = build_distance_matrix(coords)
    n = len(nodes)

    print(f"  Nodes: {n}")

    # Run GA
    t0 = time.perf_counter()
    ga_result = run_ga(matrix, n)
    ga_time = time.perf_counter() - t0

    # Run ACO
    t0 = time.perf_counter()
    aco_result = run_aco(matrix, n)
    aco_time = time.perf_counter() - t0

    # Run Hybrid
    t0 = time.perf_counter()
    hybrid_result = run_hybrid_ga_aco(matrix, n)
    hybrid_time = time.perf_counter() - t0

    ga_dist = ga_result["metrics"]["distance_km"]
    aco_dist = aco_result["metrics"]["distance_km"]
    hybrid_dist = hybrid_result["metrics"]["distance_km"]

    ga_obj = ga_result["metrics"]["objective"]
    aco_obj = aco_result["metrics"]["objective"]
    hybrid_obj = hybrid_result["metrics"]["objective"]

    print(f"\n  {'Algorithm':<18} {'Distance(km)':>14} {'Objective':>12} {'Time(s)':>10}")
    print(f"  {'-'*18} {'-'*14} {'-'*12} {'-'*10}")
    print(f"  {'GA':<18} {ga_dist:>14.4f} {ga_obj:>12.4f} {ga_time:>10.2f}")
    print(f"  {'ACO':<18} {aco_dist:>14.4f} {aco_obj:>12.4f} {aco_time:>10.2f}")
    print(f"  {'Hybrid GA-ACO':<18} {hybrid_dist:>14.4f} {hybrid_obj:>12.4f} {hybrid_time:>10.2f}")

    best_other_dist = min(ga_dist, aco_dist)
    best_other_obj = min(ga_obj, aco_obj)

    dist_margin = best_other_dist - hybrid_dist
    obj_margin = best_other_obj - hybrid_obj

    print(f"\n  Hybrid vs best standalone:")
    print(f"    Distance margin: {dist_margin:.4f} km ({(dist_margin/best_other_dist*100) if best_other_dist > 0 else 0:.2f}%)")
    print(f"    Objective margin: {obj_margin:.4f} ({(obj_margin/best_other_obj*100) if best_other_obj > 0 else 0:.2f}%)")

    if hybrid_dist <= best_other_dist:
        print(f"  [PASS] HYBRID WINS on distance!")
    else:
        print(f"  [FAIL] HYBRID LOSES on distance (by {-dist_margin:.4f} km)")

    if hybrid_obj <= best_other_obj:
        print(f"  [PASS] HYBRID WINS on objective!")
    else:
        print(f"  [FAIL] HYBRID LOSES on objective (by {-obj_margin:.4f})")

    return hybrid_dist <= best_other_dist


if __name__ == "__main__":
    all_pass = True
    for csv_file in CSV_FILES:
        if not os.path.exists(csv_file):
            print(f"\n  [SKIP] Skipping {csv_file} (not found)")
            continue
        result = test_location(csv_file)
        if not result:
            all_pass = False

    print(f"\n{'=' * 70}")
    if all_pass:
        print("  [SUCCESS] ALL LOCATIONS: Hybrid GA-ACO gives the best result!")
    else:
        print("  [WARNING] Some locations: Hybrid did not win. Further tuning needed.")
    print(f"{'=' * 70}")
