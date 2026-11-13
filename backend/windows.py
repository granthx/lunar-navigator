"""Landing-window finder: slide a mission-length window over a date range and rank.

Objectives
  balanced : reward overlap of power and comms, penalise a long dark stretch
  power    : power first
  comms    : comms first
  survive  : windows whose longest dark stretch exceeds `battery_h` are infeasible
"""
from __future__ import annotations

import numpy as np

from .visibility import metrics, runs

OBJECTIVES = ("balanced", "power", "comms", "survive")


def _window_metrics(power, comms, cs_p, cs_c, cs_b, dark_runs, gap_runs, s, L, step_h):
    e = s + L
    p = cs_p[e] - cs_p[s]
    c = cs_c[e] - cs_c[s]
    b = cs_b[e] - cs_b[s]

    def longest(rs):
        starts, ends = rs
        if starts.size == 0:
            return 0
        lo = np.searchsorted(ends, s, side="right")     # first run ending after s
        hi = np.searchsorted(starts, e, side="left")    # runs starting before e
        if hi <= lo:
            return 0
        seg_s = np.maximum(starts[lo:hi], s)
        seg_e = np.minimum(ends[lo:hi], e)
        return int((seg_e - seg_s).max())

    return {
        "power_pct": 100.0 * p / L,
        "comms_pct": 100.0 * c / L,
        "both_pct": 100.0 * b / L,
        "longest_dark_h": longest(dark_runs) * step_h,
        "longest_comms_gap_h": longest(gap_runs) * step_h,
        "hours": L * step_h,
    }


def score(m: dict, objective: str, battery_h: float | None = None) -> tuple[float, bool]:
    """Return (score, feasible). Scores are in roughly [-1, 1]."""
    dur = max(m["hours"], 1e-9)
    both, pw, cm = m["both_pct"] / 100, m["power_pct"] / 100, m["comms_pct"] / 100
    dark = m["longest_dark_h"] / dur
    gap = m["longest_comms_gap_h"] / dur
    feasible = True
    if objective == "power":
        s = pw + 0.3 * both - 0.3 * dark
    elif objective == "comms":
        s = cm + 0.3 * both - 0.3 * gap
    elif objective == "survive":
        if battery_h is None:
            raise ValueError("objective 'survive' needs battery_h")
        if m["longest_dark_h"] > battery_h:
            feasible = False
            s = -1.0 - (m["longest_dark_h"] - battery_h) / dur
        else:
            s = both + 0.5 * pw
    else:  # balanced
        s = 0.5 * both + 0.25 * pw + 0.25 * cm - 0.25 * dark
    return float(s), feasible


def find_windows(times, power, comms, duration_h: float, step_h: float = 1.0,
                 objective: str = "balanced", battery_h: float | None = None,
                 top_n: int = 5, min_separation_h: float | None = None) -> list[dict]:
    """Rank non-overlapping windows. `times` is the datetime64 array for the series."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    power = np.asarray(power, dtype=bool)
    comms = np.asarray(comms, dtype=bool)
    n = len(power)
    L = int(round(duration_h / step_h))
    if L < 1 or L > n:
        raise ValueError("window longer than the available date range")

    cs_p = np.concatenate(([0], np.cumsum(power)))
    cs_c = np.concatenate(([0], np.cumsum(comms)))
    cs_b = np.concatenate(([0], np.cumsum(power & comms)))
    dark_runs = runs(~power)
    gap_runs = runs(~comms)

    cands = []
    for s in range(0, n - L + 1):
        m = _window_metrics(power, comms, cs_p, cs_c, cs_b, dark_runs, gap_runs, s, L, step_h)
        sc, ok = score(m, objective, battery_h)
        cands.append((sc, ok, s, m))
    cands.sort(key=lambda x: (x[1], x[0]), reverse=True)   # feasible first, then score

    sep = int(round((min_separation_h if min_separation_h is not None else duration_h) / step_h))
    picked, used = [], []
    for sc, ok, s, m in cands:
        if all(abs(s - u) >= sep for u in used):
            picked.append({
                "start_index": s, "end_index": s + L,
                "start": str(times[s]), "end": str(times[min(s + L, n - 1)]),
                "score": sc, "feasible": ok, "metrics": m, "objective": objective,
            })
            used.append(s)
            if len(picked) >= top_n:
                break
    return picked
