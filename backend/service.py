"""Service layer: one place that wires DEM + sites + ephemeris + analysis, with caching.

Used by the HTTP API and by the agents' tools, so both see identical numbers.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import ephemeris as eph
from .dem import DEM, synthetic_dem
from .height_sweep import DEFAULT_HEIGHTS_M, MAX_MAST_M, height_sweep
from .horizon import compute_horizon, horizon_info
from .sites import Site, load_sites, make_demo_sites
from .uncertainty import hourly_probability, mc_visibility, window_uncertainty
from .visibility import CODE_NAMES, classify, metrics
from .windows import OBJECTIVES, find_windows

MAX_SAMPLES = 24 * 400
RMAX_M = 30_000.0

EPHEMERIS_ANALYTICAL = "analytical"
EPHEMERIS_SPICE = "spice"


class ServiceError(ValueError):
    """User-facing input problem."""


def _resolve_ephemeris(requested: str | None = None) -> tuple[str, tuple[str, ...]]:
    """Pick the ephemeris backend from an explicit value or the environment.

    `LUNAR_EPHEMERIS=spice` is opt-in and never falls back silently: a missing
    dependency or kernel file raises ServiceError with the reason.
    """
    name = requested if requested is not None else os.environ.get("LUNAR_EPHEMERIS", "")
    name = (name or "").strip().lower() or EPHEMERIS_ANALYTICAL
    if name in (EPHEMERIS_ANALYTICAL, "meeus"):
        return EPHEMERIS_ANALYTICAL, ()
    if name != EPHEMERIS_SPICE:
        raise ServiceError(
            f"LUNAR_EPHEMERIS must be '{EPHEMERIS_ANALYTICAL}' or '{EPHEMERIS_SPICE}' "
            f"(got '{name}')"
        )
    if importlib.util.find_spec("spiceypy") is None:
        raise ServiceError(
            "LUNAR_EPHEMERIS=spice requires spiceypy; install it with 'pip install spiceypy'"
        )
    raw = os.environ.get("LUNAR_SPICE_KERNELS", "").strip()
    kernels = (
        [p.strip() for p in raw.split(os.pathsep) if p.strip()]
        if raw else eph.default_spice_kernels()
    )
    missing = [p for p in kernels if not os.path.isfile(os.path.expanduser(p))]
    if missing:
        raise ServiceError(
            "LUNAR_EPHEMERIS=spice needs the DE440 kernel set, but these files are missing: "
            + ", ".join(missing)
            + f". Set LUNAR_SPICE_KERNELS to a '{os.pathsep}'-separated list of the five kernels "
              "(see scripts/README_DATA.md)."
        )
    try:
        eph.load_spice_kernels(kernels)
    except Exception as exc:  # noqa: BLE001 - report the actual kernel error
        raise ServiceError(f"SPICE kernels could not be loaded: {exc}") from exc
    return EPHEMERIS_SPICE, tuple(kernels)


def _parse_day(s: str) -> np.datetime64:
    try:
        return np.datetime64(s[:10] if len(s) > 10 else s, "D").astype("datetime64[h]")
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"could not read date '{s}' (use YYYY-MM-DD)") from exc


def _height_in_range(value) -> float:
    try:
        h = float(value)
    except (TypeError, ValueError) as exc:
        raise ServiceError(f"height must be a number between 0 and {MAX_MAST_M:g} m") from exc
    if not np.isfinite(h) or h < 0 or h > MAX_MAST_M:
        raise ServiceError(f"height must be between 0 and {MAX_MAST_M:g} m")
    return h


class Service:
    def __init__(self, dem: DEM | None = None, sites: list[Site] | None = None,
                 ephemeris: str | None = None):
        self.ephemeris, self._kernels = _resolve_ephemeris(ephemeris)
        if dem is None:
            path = os.environ.get("LUNAR_DEM")
            dem = DEM.from_npz(path) if path else synthetic_dem()
        self.dem = dem
        if sites is None:
            sp = os.environ.get("LUNAR_SITES")
            sites = load_sites(sp) if sp else make_demo_sites(dem)
        self.sites = {s.id: s for s in sites}
        self._hor, self._series, self._mc = {}, {}, {}

    # ------------------------------------------------------------------ meta
    def meta(self) -> dict:
        warnings = []
        if self.dem.synthetic:
            warnings.append("Terrain is SYNTHETIC demo data, not real lunar terrain. "
                            "Results show how the tool works, not real site performance.")
        if self.ephemeris == EPHEMERIS_SPICE:
            ephemeris = "SPICE DE440 (MOON_ME frame, LT+S)"
        else:
            ephemeris = "analytical (Meeus + IAU 2015 lunar orientation)"
            warnings.append("Sun/Earth directions use an analytical ephemeris (about 0.05 deg class), "
                            "not SPICE. See scripts/README_DATA.md to switch.")
        demo_sites = [s for s in self.sites.values() if not s.verified and not s.representative]
        if demo_sites:
            warnings.append("Some site coordinates are unverified demo values.")
        representative = [s for s in self.sites.values() if s.representative]
        if representative:
            warnings.append(
                f"{len(representative)} site point(s) are representative points inside official "
                "region polygons, not certified landing coordinates."
            )
        out = {"dem_label": self.dem.label, "synthetic": self.dem.synthetic,
               "px_m": self.dem.px_m, "dem_radius_km": self.dem.radius_m / 1000.0,
               "ephemeris": ephemeris, "ephemeris_backend": self.ephemeris,
               "sites": [s.to_dict() for s in self.sites.values()],
               "objectives": list(OBJECTIVES), "default_heights_m": list(DEFAULT_HEIGHTS_M),
               "max_height_m": MAX_MAST_M, "warnings": warnings}
        if self.ephemeris == EPHEMERIS_SPICE:
            out["ephemeris_kernels"] = [Path(k).name for k in self._kernels]
        return out

    def site(self, site_id: str) -> Site:
        if site_id not in self.sites:
            raise ServiceError(f"unknown site '{site_id}'. Known: {', '.join(self.sites)}")
        return self.sites[site_id]

    # --------------------------------------------------------------- horizon
    def horizon(self, site_id: str, height_m: float = 0.0):
        height_m = _height_in_range(height_m)
        key = (site_id, height_m)
        if key not in self._hor:
            s = self.site(site_id)
            self._hor[key] = compute_horizon(self.dem, s.lat, s.lon, height_m, RMAX_M, 1.0)
        return self._hor[key]

    # ---------------------------------------------------------------- series
    def _grid(self, start: str, end: str, step_h: float):
        t0, t1 = _parse_day(start), _parse_day(end)
        if t1 <= t0:
            raise ServiceError("end date must be after start date")
        step_min = int(round(step_h * 60))
        if step_min < 30:
            raise ServiceError("step must be at least 0.5 hours")
        n = int((t1 - t0) / np.timedelta64(step_min, "m"))
        if n < 1:
            raise ServiceError("date range is shorter than one step; widen the range or reduce the step")
        if n > MAX_SAMPLES:
            raise ServiceError(f"range too long for this step (max {MAX_SAMPLES} samples); "
                               "shorten the range or increase the step")
        times = t0.astype("datetime64[m]") + np.arange(n) * np.timedelta64(step_min, "m")
        return times, step_min / 60.0

    def series(self, site_id: str, start: str, end: str, step_h: float = 1.0) -> dict:
        times, step_h = self._grid(start, end, step_h)
        key = (site_id, str(times[0]), len(times), step_h)
        if key not in self._series:
            s = self.site(site_id)
            if self.ephemeris == EPHEMERIS_SPICE:
                r = eph.spice_backend(s.lat, s.lon, times, self._kernels)
            else:
                r = eph.sun_earth_azel(s.lat, s.lon, times)
            r["times"], r["step_h"] = times, step_h
            self._series[key] = r
        return self._series[key]

    def visibility(self, site_id, start, end, step_h=1.0, height_m=0.0,
                   sun_margin_deg=0.0, earth_margin_deg=0.0) -> dict:
        ser = self.series(site_id, start, end, step_h)
        az, hor = self.horizon(site_id, height_m)
        c = classify(ser["sun_az"], ser["sun_el"], ser["earth_az"], ser["earth_el"], az, hor,
                     sun_margin_deg, earth_margin_deg)
        return {"series": ser, "classified": c, "metrics": metrics(c["power"], c["comms"], ser["step_h"]),
                "horizon": (az, hor)}

    # --------------------------------------------------------------- windows
    def windows(self, site_id, start, end, duration_h, objective="balanced", battery_h=None,
                height_m=0.0, step_h=1.0, top_n=3, uncertainty=True, mc_n=30,
                sigma_m=8.0, corr_m=500.0) -> dict:
        if objective not in OBJECTIVES:
            raise ServiceError(f"objective must be one of {list(OBJECTIVES)}")
        if objective == "survive" and battery_h is None:
            raise ServiceError("objective 'survive' needs battery_h")
        v = self.visibility(site_id, start, end, step_h, height_m)
        ser, c = v["series"], v["classified"]
        if duration_h > len(ser["times"]) * ser["step_h"]:
            raise ServiceError("mission duration is longer than the selected date range")
        wins = find_windows(ser["times"], c["power"], c["comms"], duration_h, ser["step_h"],
                            objective, battery_h, top_n)
        if uncertainty and wins:
            mc = self._mc_for(site_id, ser, height_m, mc_n, sigma_m, corr_m)
            for w in wins:
                w["uncertainty"] = window_uncertainty(mc, w["start_index"], w["end_index"], ser["step_h"])
        info = horizon_info(self.dem, self.site(site_id).lat, self.site(site_id).lon, RMAX_M)
        return {"site_id": site_id, "windows": wins, "objective": objective, "battery_h": battery_h,
                "duration_h": duration_h, "height_m": height_m, "overall": v["metrics"],
                "data_notes": info, "n_samples": len(ser["times"]), "step_h": ser["step_h"]}

    def _mc_for(self, site_id, ser, height_m, mc_n, sigma_m, corr_m):
        key = (site_id, str(ser["times"][0]), len(ser["times"]), ser["step_h"], float(height_m),
               mc_n, sigma_m, corr_m)
        if key not in self._mc:
            s = self.site(site_id)
            self._mc[key] = mc_visibility(self.dem, s.lat, s.lon, ser, height_m, mc_n,
                                          sigma_m, corr_m, rmax_m=RMAX_M)
        return self._mc[key]

    def window_probability(self, site_id, start, end, duration_h, rank=0, **kw) -> dict:
        """Hourly P(both) across terrain realizations for the rank-th window (for confidence bands)."""
        kw = dict(kw)
        kw["uncertainty"] = True
        res = self.windows(site_id, start, end, duration_h, **kw)
        if not res["windows"]:
            raise ServiceError("no window found")
        ser = self.series(site_id, start, end, kw.get("step_h", 1.0))
        mc = self._mc_for(site_id, ser, kw.get("height_m", 0.0), kw.get("mc_n", 30),
                          kw.get("sigma_m", 8.0), kw.get("corr_m", 500.0))
        prob = hourly_probability(mc)
        w = res["windows"][min(rank, len(res["windows"]) - 1)]
        sl = slice(w["start_index"], w["end_index"])
        return {"window": w, "times": [str(t) for t in ser["times"][sl]],
                "p_both": np.round(prob["p_both"][sl], 3).tolist(),
                "p_power": np.round(prob["p_power"][sl], 3).tolist(),
                "p_comms": np.round(prob["p_comms"][sl], 3).tolist()}

    # ---------------------------------------------------------------- height
    def height(self, site_id, start, end, heights=None, window_start=None, window_end=None,
               step_h=1.0) -> dict:
        ser = self.series(site_id, start, end, step_h)
        s = self.site(site_id)
        raw = DEFAULT_HEIGHTS_M if heights is None else heights
        if isinstance(raw, (int, float)):
            raw = (raw,)
        try:
            checked = tuple(_height_in_range(h) for h in raw)
        except TypeError as exc:
            raise ServiceError("heights must be a list of numbers") from exc
        if not checked:
            raise ServiceError("provide at least one height")
        sl = None
        if window_start is not None and window_end is not None:
            sl = slice(int(window_start), int(window_end))
        out = height_sweep(self.dem, s.lat, s.lon, ser, checked,
                           sl, RMAX_M, 1.0, ser["step_h"])
        out["site_id"] = site_id
        return out

    # ------------------------------------------------------------ transport
    def series_payload(self, site_ids, start, end, step_h=1.0, height_m=0.0) -> dict:
        out = {"sites": {}, "code_names": CODE_NAMES}
        for sid in site_ids:
            v = self.visibility(sid, start, end, step_h, height_m)
            ser, c = v["series"], v["classified"]
            az, hor = v["horizon"]
            r3 = lambda a: np.round(a, 3).tolist()  # noqa: E731
            out["sites"][sid] = {
                "site": self.site(sid).to_dict(),
                "times": [str(t) for t in ser["times"]],
                "step_h": ser["step_h"],
                "code": c["code"].astype(int).tolist(),
                "sun_az": r3(ser["sun_az"]), "sun_el": r3(ser["sun_el"]),
                "earth_az": r3(ser["earth_az"]), "earth_el": r3(ser["earth_el"]),
                "horizon_az": az.tolist(), "horizon_el": r3(hor),
                "metrics": v["metrics"],
                "data_notes": horizon_info(self.dem, self.site(sid).lat, self.site(sid).lon, RMAX_M),
            }
        return out


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
