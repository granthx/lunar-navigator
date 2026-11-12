"""Terrain horizon profile at a site: max elevation angle of terrain per azimuth."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates

from .dem import DEM, R_MOON_M


def compute_horizon(dem: DEM, lat_deg: float, lon_deg: float, height_m: float = 0.0,
                    rmax_m: float = 30_000.0, az_step_deg: float = 1.0):
    """Return (azimuths_deg, horizon_elevation_deg).

    Azimuth: from local north, clockwise through east. Each ray is marched out
    to `rmax_m` (or until it leaves the DEM) in steps of one pixel. Elevation of
    terrain at distance r includes the curvature drop r^2 / 2R. Rays that leave
    the DEM contribute nothing beyond the edge; this is an edge effect, reported
    through `edge_limited` in `horizon_info`.
    """
    az = np.arange(0.0, 360.0, az_step_deg)
    r = np.arange(dem.px_m, rmax_m, dem.px_m)
    phi = np.radians(lat_deg)
    lam = np.radians(lon_deg)
    delta = r / R_MOON_M

    A = np.radians(az)[:, None]
    D = delta[None, :]
    lat2 = np.arcsin(np.sin(phi) * np.cos(D) + np.cos(phi) * np.sin(D) * np.cos(A))
    lon2 = lam + np.arctan2(np.sin(A) * np.sin(D) * np.cos(phi),
                            np.cos(D) - np.sin(phi) * np.sin(lat2))

    x, y = dem.project(np.degrees(lat2), np.degrees(lon2))
    col, row = dem.to_pixels(x, y)
    zt = map_coordinates(dem.z, [row.ravel(), col.ravel()], order=1,
                         mode="constant", cval=np.nan).reshape(row.shape)

    z0 = float(dem.sample_latlon(lat_deg, lon_deg)[0])
    if np.isnan(z0):
        raise ValueError("site lies outside the DEM")
    z_obs = z0 + height_m
    ang = np.degrees(np.arctan2(zt - z_obs - (r[None, :] ** 2) / (2 * R_MOON_M), r[None, :]))
    hor = np.nanmax(np.where(np.isnan(ang), -np.inf, ang), axis=1)
    hor = np.where(np.isfinite(hor), hor, 0.0)
    return az, hor


def horizon_info(dem: DEM, lat_deg: float, lon_deg: float, rmax_m: float = 30_000.0) -> dict:
    """Describe data coverage at a site (how far rays can travel before leaving the DEM)."""
    x, y = dem.project(lat_deg, lon_deg)
    col, row = dem.to_pixels(x, y)
    h, w = dem.z.shape
    to_edge = min(col, w - 1 - col, row, h - 1 - row) * dem.px_m
    return {"distance_to_dem_edge_m": float(to_edge),
            "edge_limited": bool(to_edge < rmax_m),
            "synthetic": dem.synthetic, "dem_label": dem.label}


def horizon_at(az_grid: np.ndarray, hor: np.ndarray, az_query) -> np.ndarray:
    """Interpolate a periodic horizon profile at arbitrary azimuths."""
    return np.interp(np.asarray(az_query) % 360.0, az_grid, hor, period=360.0)
