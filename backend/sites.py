"""Candidate site registry.

The built-in sites are DEMO sites placed on the synthetic terrain. They are NOT
real NASA candidate sites. To use real sites, create a JSON file (see
backend/data/sites_template.json), fill in coordinates verified against NASA's
official Artemis documentation, and load it with `load_sites`.
"""
from __future__ import annotations

import json

import numpy as np
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    lat: float          # selenographic latitude, deg (negative = south)
    lon: float          # selenographic longitude, deg east (0-360)
    verified: bool = False
    note: str = ""
    representative: bool = False  # a point inside a region, not a certified landing coordinate
    source: str = ""              # provenance for the coordinates

    def to_dict(self):
        return asdict(self)


DEMO_SITES = [
    Site("demo_a", "Demo Site A", -89.70, 20.0, False, "synthetic demo site"),
    Site("demo_b", "Demo Site B", -89.45, 135.0, False, "synthetic demo site"),
    Site("demo_c", "Demo Site C", -89.15, 250.0, False, "synthetic demo site"),
    Site("demo_d", "Demo Site D", -88.95, 330.0, False, "synthetic demo site"),
    Site("demo_e", "Demo Site E", -89.85, 80.0, False, "synthetic demo site"),
]


def _snap(dem, lat, lon, radius_m, mode):
    """Move a nominal position to the highest (or lowest) nearby terrain."""
    x, y = dem.project(lat, lon)
    col, row = dem.to_pixels(x, y)
    r = int(radius_m / dem.px_m)
    r0, r1 = max(0, int(row) - r), min(dem.z.shape[0], int(row) + r + 1)
    c0, c1 = max(0, int(col) - r), min(dem.z.shape[1], int(col) + r + 1)
    win = dem.z[r0:r1, c0:c1]
    idx = np.argmax(win) if mode == "max" else np.argmin(win)
    rr, cc = np.unravel_index(idx, win.shape)
    xs = (c0 + cc - dem.cx) * dem.px_m
    ys = (dem.cy - (r0 + rr)) * dem.px_m
    return dem.unproject(xs, ys)


def make_demo_sites(dem) -> list[Site]:
    """Demo sites placed on the synthetic terrain: four on high ground, one in a low spot.

    Positions are snapped to local terrain extrema, so they are demo geometry only.
    """
    nominal = [("demo_a", "Demo Site A", -89.70, 20.0, "max"),
               ("demo_b", "Demo Site B", -89.45, 135.0, "max"),
               ("demo_c", "Demo Site C", -89.15, 250.0, "max"),
               ("demo_d", "Demo Site D", -88.95, 330.0, "max"),
               ("demo_e", "Demo Site E (low ground)", -89.85, 80.0, "min")]
    out = []
    for sid, name, la, lo, mode in nominal:
        lat, lon = _snap(dem, la, lo, 4000.0, mode)
        out.append(Site(sid, name, round(float(lat), 4), round(float(lon), 3), False,
                        "synthetic demo site on synthetic terrain"))
    return out


def load_sites(path: str) -> list[Site]:
    with open(path) as f:
        raw = json.load(f)
    return [Site(**s) for s in raw["sites"]]
