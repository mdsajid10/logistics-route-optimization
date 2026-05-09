from __future__ import annotations

from io import BytesIO
from typing import Dict, List

import pandas as pd

LAT_CANDIDATES = {"latitude", "lat", "y", "lat_dd"}
LON_CANDIDATES = {"longitude", "lon", "lng", "long", "x", "lon_dd"}


def _normalize(name: str) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum() or ch == "_")


def _find_column(columns: List[str], candidates: set[str]) -> str | None:
    normalized = {_normalize(col): col for col in columns}
    for key, original in normalized.items():
        if key in candidates:
            return original
    return None


def parse_csv_bytes(csv_bytes: bytes) -> Dict:
    """Parse CSV and extract only node fields needed for optimization."""
    df = pd.read_csv(BytesIO(csv_bytes))
    if df.empty:
        raise ValueError("CSV file is empty.")

    lat_col = _find_column(df.columns.tolist(), LAT_CANDIDATES)
    lon_col = _find_column(df.columns.tolist(), LON_CANDIDATES)

    if lat_col is None or lon_col is None:
        raise ValueError("Could not find latitude/longitude columns in CSV.")

    working = df[[lat_col, lon_col]].copy()
    optional_id_col = next((col for col in df.columns if _normalize(col) in {"orderid", "order_id", "id"}), None)
    optional_demand_col = next((col for col in df.columns if _normalize(col) in {"demand", "qty", "quantity"}), None)

    if optional_id_col:
        working["order_id"] = df[optional_id_col]
    else:
        working["order_id"] = [f"ORD-{i + 1}" for i in range(len(working))]

    if optional_demand_col:
        working["demand"] = pd.to_numeric(df[optional_demand_col], errors="coerce").fillna(0.0)
    else:
        working["demand"] = 0.0

    working = working.rename(columns={lat_col: "latitude", lon_col: "longitude"})
    working["latitude"] = pd.to_numeric(working["latitude"], errors="coerce")
    working["longitude"] = pd.to_numeric(working["longitude"], errors="coerce")
    working = working.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)

    if len(working) < 2:
        raise ValueError("Need at least two valid locations to optimize routes.")

    records = [
        {
            "node_id": int(i),
            "order_id": str(row["order_id"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "demand": float(row["demand"]),
        }
        for i, row in working.iterrows()
    ]

    return {
        "node_count": len(records),
        "nodes": records,
    }
