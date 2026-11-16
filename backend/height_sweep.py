"""Mast-height trade-off: how do power/comms change if the antenna or panel is raised?"""
from __future__ import annotations

from .dem import DEM
from .horizon import compute_horizon
from .visibility import classify, metrics

MAX_MAST_M = 15.0
DEFAULT_HEIGHTS_M = (0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0)


def height_sweep(dem: DEM, lat: float, lon: float, series: dict, heights=DEFAULT_HEIGHTS_M,
                 index_slice: slice | None = None, rmax_m: float = 30_000.0,
                 az_step_deg: float = 1.0, step_h: float = 1.0,
                 flip_threshold_pct: float = 10.0) -> dict:
    """`series` holds sun_az/sun_el/earth_az/earth_el arrays (from ephemeris.sun_earth_azel)."""
    sl = index_slice or slice(None)
    rows = []
    for h in heights:
        az, hor = compute_horizon(dem, lat, lon, h, rmax_m, az_step_deg)
        c = classify(series["sun_az"][sl], series["sun_el"][sl],
                     series["earth_az"][sl], series["earth_el"][sl], az, hor)
        m = metrics(c["power"], c["comms"], step_h)
        m["height_m"] = float(h)
        rows.append(m)

    if not rows:
        raise ValueError("at least one height is required")

    flips = {}
    for key in ("power_pct", "comms_pct", "both_pct"):
        best = None
        for a, b in zip(rows[:-1], rows[1:]):
            jump = b[key] - a[key]
            if best is None or jump > best["jump_pct"]:
                best = {"from_height_m": a["height_m"], "to_height_m": b["height_m"],
                        "jump_pct": jump, "from_pct": a[key], "to_pct": b[key]}
        if best is None:  # a single height has no pair to compare
            only = rows[0]
            best = {"from_height_m": only["height_m"], "to_height_m": only["height_m"],
                    "jump_pct": 0.0, "from_pct": only[key], "to_pct": only[key]}
        best["is_flip"] = bool(best["jump_pct"] >= flip_threshold_pct)
        flips[key] = best
    return {"rows": rows, "biggest_jumps": flips, "flip_threshold_pct": flip_threshold_pct}
