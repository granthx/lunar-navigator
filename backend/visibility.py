"""Power / comms visibility classification and summary metrics."""
from __future__ import annotations

import numpy as np

from .horizon import horizon_at

NEITHER, POWER_ONLY, COMMS_ONLY, BOTH = 0, 1, 2, 3
CODE_NAMES = {NEITHER: "neither", POWER_ONLY: "power only", COMMS_ONLY: "comms only", BOTH: "power + comms"}

# Mean angular radii as seen from the Moon (deg). The Earth is large (~0.95 deg
# radius), the Sun ~0.27 deg. Default model treats each body as a point at its
# centre; `*_margin_deg` lets the user demand extra clearance (e.g. antenna beam
# or panel tilt margin).
SUN_RADIUS_DEG = 0.27
EARTH_RADIUS_DEG = 0.95


def classify(sun_az, sun_el, earth_az, earth_el, az_grid, hor,
             sun_margin_deg: float = 0.0, earth_margin_deg: float = 0.0) -> dict:
    sun_clear = np.asarray(sun_el) - horizon_at(az_grid, hor, sun_az)
    earth_clear = np.asarray(earth_el) - horizon_at(az_grid, hor, earth_az)
    power = sun_clear > sun_margin_deg
    comms = earth_clear > earth_margin_deg
    code = power.astype(np.int8) + 2 * comms.astype(np.int8)
    return {"power": power, "comms": comms, "code": code,
            "sun_clearance_deg": sun_clear, "earth_clearance_deg": earth_clear}


def longest_run(mask: np.ndarray) -> int:
    """Length (samples) of the longest run of True."""
    m = np.asarray(mask, dtype=np.int8)
    if m.size == 0:
        return 0
    d = np.diff(np.concatenate(([0], m, [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return int((ends - starts).max()) if starts.size else 0


def metrics(power: np.ndarray, comms: np.ndarray, step_h: float = 1.0) -> dict:
    n = max(len(power), 1)
    both = power & comms
    return {
        "power_pct": 100.0 * float(np.sum(power)) / n,
        "comms_pct": 100.0 * float(np.sum(comms)) / n,
        "both_pct": 100.0 * float(np.sum(both)) / n,
        "longest_dark_h": longest_run(~power) * step_h,
        "longest_comms_gap_h": longest_run(~comms) * step_h,
        "hours": n * step_h,
    }


def runs(mask: np.ndarray):
    """(start, end_exclusive) index pairs of True runs."""
    m = np.asarray(mask, dtype=np.int8)
    d = np.diff(np.concatenate(([0], m, [0])))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)
