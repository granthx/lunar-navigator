"""Pre-compute and print horizon metrics for all 9 real candidate sites.

Usage (from project root):
    $env:LUNAR_DEM  = "backend/data/lunar_south_pole_80m.npz"
    $env:LUNAR_SITES = "backend/data/sites_real.json"
    $env:LUNAR_EPHEMERIS = "spice"
    python scripts/site_summary.py [--range 2027-01-01 2027-04-01] [--json]

Output: for each site, the horizon profile summary (max/mean terrain elevation
angle in each quadrant) and visibility metrics over the requested date range.

This is a convenience / reporting script; it does not modify any source files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# allow running from the project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.horizon import horizon_info
from backend.service import Service, today_utc


def _parse_args():
    p = argparse.ArgumentParser(description="Site horizon + visibility summary")
    p.add_argument("--range", nargs=2, metavar=("START", "END"),
                   default=["2027-01-01", "2027-04-01"],
                   help="Date range for visibility metrics (default: 2027-01-01 to 2027-04-01)")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Print machine-readable JSON instead of a table")
    return p.parse_args()


def _quadrant_summary(az, hor):
    """Return mean and max horizon elevation per compass quadrant (N/E/S/W)."""
    import numpy as np
    az = az % 360
    out = {}
    for name, (lo, hi) in [("N", (315, 45)), ("E", (45, 135)), ("S", (135, 225)), ("W", (225, 315))]:
        if lo < hi:
            mask = (az >= lo) & (az < hi)
        else:  # wraps 315-360-0-45
            mask = (az >= lo) | (az < hi)
        vals = hor[mask]
        out[name] = {"mean_el": float(round(vals.mean(), 2)), "max_el": float(round(vals.max(), 2))}
    return out


def main():
    args = _parse_args()
    start, end = args.range

    svc = Service()
    meta = svc.meta()

    rows = []
    for site in meta["sites"]:
        sid = site["id"]
        # Horizon profile
        az, hor = svc.horizon(sid)
        qsum = _quadrant_summary(az, hor)
        info = horizon_info(svc.dem, site["lat"], site["lon"], 30_000.0)

        # Visibility over the date range
        vis = svc.visibility(sid, start, end)
        m = vis["metrics"]

        rows.append({
            "id": sid,
            "name": site["name"],
            "lat": site["lat"],
            "lon": site["lon"],
            "representative": site.get("representative", False),
            "max_horizon_el_deg": float(round(max(hor), 2)),
            "mean_horizon_el_deg": float(round(sum(hor) / len(hor), 2)),
            "edge_limited": info["edge_limited"],
            "quadrants": qsum,
            "visibility": {
                "range": f"{start} → {end}",
                "power_pct": round(m["power_pct"], 1),
                "comms_pct": round(m["comms_pct"], 1),
                "both_pct": round(m["both_pct"], 1),
                "longest_dark_h": round(m["longest_dark_h"], 1),
                "longest_comms_gap_h": round(m["longest_comms_gap_h"], 1),
            },
        })

    if args.as_json:
        print(json.dumps({"sites": rows, "dem": meta["dem_label"],
                          "ephemeris": meta["ephemeris_backend"],
                          "range": f"{start} → {end}"}, indent=2))
        return

    # ---- plain table ----
    print(f"\nSite summary  |  DEM: {meta['dem_label']}  |  Ephemeris: {meta['ephemeris_backend']}")
    print(f"Visibility range: {start} → {end}\n")
    hdr = f"{'Site':<30} {'lat':>7} {'lon':>7} {'max_el':>6} {'power%':>7} {'comms%':>7} {'both%':>7} {'dark_h':>7} {'edge'}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        v = r["visibility"]
        edge = "YES" if r["edge_limited"] else "no"
        print(f"{r['name']:<30} {r['lat']:>7.2f} {r['lon']:>7.2f} "
              f"{r['max_horizon_el_deg']:>6.1f} "
              f"{v['power_pct']:>7.1f} {v['comms_pct']:>7.1f} {v['both_pct']:>7.1f} "
              f"{v['longest_dark_h']:>7.1f} {edge:>5}")

    print("\nQuadrant max horizon elevation (°):")
    print(f"{'Site':<30} {'N':>6} {'E':>6} {'S':>6} {'W':>6}")
    print("-" * 54)
    for r in rows:
        q = r["quadrants"]
        print(f"{r['name']:<30} "
              f"{q['N']['max_el']:>6.1f} {q['E']['max_el']:>6.1f} "
              f"{q['S']['max_el']:>6.1f} {q['W']['max_el']:>6.1f}")

    print(f"\nNotes:")
    print(f"  max_el   = maximum terrain horizon elevation angle in degrees (higher = more obstruction)")
    print(f"  edge     = YES if the DEM boundary cuts the 30 km horizon search")
    print(f"  power%   = fraction of hours when the Sun is above the terrain horizon")
    print(f"  comms%   = fraction of hours when Earth is above the terrain horizon")
    print(f"  both%    = fraction of hours when BOTH are above the horizon")
    print(f"  dark_h   = longest continuous stretch (hours) with no sunlight\n")


if __name__ == "__main__":
    main()

