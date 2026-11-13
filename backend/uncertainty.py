"""Honest uncertainty: Monte Carlo over terrain error.

What this covers: spatially correlated vertical error in the elevation model
(default 8 m, correlation length 500 m - chosen as a plausible LOLA-class
figure, NOT a measured value; set from the data product's documentation).
What it does NOT cover: ephemeris error, lander pointing error, regolith or
dust effects, or terrain beyond the DEM edge. The UI must say so.
"""
from __future__ import annotations

import numpy as np

from .dem import DEM
from .horizon import compute_horizon
from .visibility import classify, metrics


def mc_visibility(dem: DEM, lat: float, lon: float, series: dict, height_m: float = 0.0,
                  n: int = 30, sigma_m: float = 8.0, corr_m: float = 500.0, seed: int = 0,
                  rmax_m: float = 30_000.0, az_step_deg: float = 2.0) -> dict:
    rng = np.random.default_rng(seed)
    local = dem.crop_around_latlon(lat, lon, rmax_m)
    corr_px = max(corr_m / dem.px_m, 0.5)
    P, C = [], []
    for _ in range(n):
        d = local.perturbed(sigma_m, corr_px, rng)
        az, hor = compute_horizon(d, lat, lon, height_m, rmax_m, az_step_deg)
        c = classify(series["sun_az"], series["sun_el"], series["earth_az"], series["earth_el"], az, hor)
        P.append(c["power"])
        C.append(c["comms"])
    return {"power": np.array(P), "comms": np.array(C), "n": n,
            "sigma_m": sigma_m, "corr_m": corr_m}


def hourly_probability(mc: dict) -> dict:
    return {"p_power": mc["power"].mean(axis=0), "p_comms": mc["comms"].mean(axis=0),
            "p_both": (mc["power"] & mc["comms"]).mean(axis=0)}


def window_uncertainty(mc: dict, start: int, end: int, step_h: float = 1.0) -> dict:
    """Distribution of window metrics across terrain realizations + robustness label."""
    per = [metrics(mc["power"][i, start:end], mc["comms"][i, start:end], step_h)
           for i in range(mc["n"])]
    out = {}
    for key in ("power_pct", "comms_pct", "both_pct", "longest_dark_h", "longest_comms_gap_h"):
        v = np.array([p[key] for p in per])
        out[key] = {"p10": float(np.percentile(v, 10)), "p50": float(np.percentile(v, 50)),
                    "p90": float(np.percentile(v, 90))}
    spread = out["both_pct"]["p90"] - out["both_pct"]["p10"]
    # heuristic thresholds (percentage points of the window): documented, tunable
    out["robustness"] = "robust" if spread <= 10 else ("moderate" if spread <= 25 else "fragile")
    out["both_spread_pct_points"] = float(spread)
    out["realizations"] = mc["n"]
    out["assumptions"] = {"vertical_sigma_m": mc["sigma_m"], "correlation_length_m": mc["corr_m"]}
    return out
