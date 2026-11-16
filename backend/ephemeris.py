"""Sun and Earth directions as seen from a site on the Moon.

Two backends produce the same output shape:

  * `sun_earth_azel`: pure-numpy analytical approximation (default).
  * `spice_backend`: NAIF SPICE with DE440 kernels.

The analytical path uses Meeus, Astronomical Algorithms ch. 25 (Sun) and ch. 47
(Moon), plus the IAU 2015 lunar rotation model (Archinal et al. 2018). Its
accuracy is a few hundredths of a degree, adequate for horizon features of a
degree or more but NOT a substitute for SPICE when precision matters. The
development sandbox originally could not download kernels; Phase 3 added a
tested SPICE path, selected through the service layer.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

R_MOON_KM = 1737.4
AU_KM = 149597870.7
TT_MINUS_UTC_S = 69.184  # 37 s leap seconds + 32.184 s (valid since 2017)
J2000_JD = 2451545.0

SPICE_KERNEL_FILES = (
    "naif0012.tls",
    "de440s.bsp",
    "moon_pa_de440_200625.bpc",
    "moon_de440_250416.tf",
    "pck00011.tpc",
)
SPICE_KERNEL_DIR = Path(__file__).resolve().parent / "data" / "spice"

_SPICE_LOADED: tuple[str, ...] | None = None

# --------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------


def jd_tt(times) -> np.ndarray:
    """UTC datetime64 array -> Julian date (TT)."""
    t = np.asarray(times).astype("datetime64[s]")
    secs = t.astype(np.int64).astype(float)
    return 2440587.5 + (secs + TT_MINUS_UTC_S) / 86400.0


# --------------------------------------------------------------------------
# rotation helpers (active rotations unless noted), stacked over time axis
# --------------------------------------------------------------------------


def _rz(a):
    a = np.asarray(a, dtype=float)
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    m[..., 0, 0] = c
    m[..., 0, 1] = -s
    m[..., 1, 0] = s
    m[..., 1, 1] = c
    m[..., 2, 2] = 1.0
    return m


def _ry(a):
    a = np.asarray(a, dtype=float)
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    m[..., 0, 0] = c
    m[..., 0, 2] = s
    m[..., 1, 1] = 1.0
    m[..., 2, 0] = -s
    m[..., 2, 2] = c
    return m


def _rx(a):
    a = np.asarray(a, dtype=float)
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    m[..., 0, 0] = 1.0
    m[..., 1, 1] = c
    m[..., 1, 2] = -s
    m[..., 2, 1] = s
    m[..., 2, 2] = c
    return m


# --------------------------------------------------------------------------
# Sun (Meeus ch. 25)
# --------------------------------------------------------------------------


def sun_geocentric_ecliptic(T):
    """Apparent geocentric Sun: ecliptic longitude (deg, of date) and distance (AU)."""
    T = np.asarray(T, dtype=float)
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T**2
    M = np.radians(357.52911 + 35999.05029 * T - 0.0001537 * T**2)
    e = 0.016708634 - 0.000042037 * T - 0.0000001267 * T**2
    C = (
        (1.914602 - 0.004817 * T - 0.000014 * T**2) * np.sin(M)
        + (0.019993 - 0.000101 * T) * np.sin(2 * M)
        + 0.000289 * np.sin(3 * M)
    )
    true_lon = L0 + C
    nu = M + np.radians(C)
    R = 1.000001018 * (1 - e**2) / (1 + e * np.cos(nu))
    omega = np.radians(125.04 - 1934.136 * T)
    app_lon = true_lon - 0.00569 - 0.00478 * np.sin(omega)
    return app_lon % 360.0, R


# --------------------------------------------------------------------------
# Moon (Meeus ch. 47, truncated)
# --------------------------------------------------------------------------

# (D, M, M', F, coefficient)  longitude: 1e-6 deg, sin ; distance: 1e-3 km, cos
_LON = [
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314),
    (0, 0, 2, 0, 213618), (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332),
    (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066), (2, 0, 1, 0, 53322),
    (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528),
    (0, 0, 1, -2, 10980), (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034),
    (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888), (2, 1, 0, 0, -6766),
    (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036),
    (2, 0, 2, 0, 3994), (4, 0, 0, 0, 3861), (2, 0, -3, 0, 3665),
    (0, 1, -2, 0, -2689), (2, 0, -1, 2, -2602), (2, -1, -2, 0, 2390),
    (1, 0, 1, 0, -2348), (2, -2, 0, 0, 2236), (0, 1, 2, 0, -2120),
    (0, 2, 0, 0, -2069), (2, -2, -1, 0, 2048), (2, 0, 1, -2, -1773),
    (2, 0, 0, 2, -1595), (4, -1, -1, 0, 1215), (0, 0, 2, 2, -1110),
    (3, 0, -1, 0, -892), (2, 1, 1, 0, -810), (4, -1, -2, 0, 759),
    (0, 2, -1, 0, -713), (2, 2, -1, 0, -700), (2, 1, -2, 0, 691),
    (2, -1, 0, -2, 596), (4, 0, 1, 0, 549), (0, 0, 4, 0, 537),
    (4, -1, 0, 0, 520), (1, 0, -2, 0, -487), (2, 1, 0, -2, -399),
    (0, 0, 2, -2, -381), (1, 1, 1, 0, 351), (3, 0, -2, 0, -340),
    (4, 0, -3, 0, 330), (2, -1, 2, 0, 327), (0, 2, 1, 0, -323),
    (1, 1, -1, 0, 299), (2, 0, 3, 0, 294),
]
_LAT = [
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211), (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794), (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107), (4, 0, 0, -1, 1021), (4, 0, -1, 1, 833),
]
_DIST = [
    (0, 0, 1, 0, -20905355), (2, 0, -1, 0, -3699111), (2, 0, 0, 0, -2955968),
    (0, 0, 2, 0, -569925), (0, 1, 0, 0, 48888), (0, 0, 0, 2, -3149),
    (2, 0, -2, 0, 246158), (2, -1, -1, 0, -152138), (2, 0, 1, 0, -170733),
    (2, -1, 0, 0, -204586), (0, 1, -1, 0, -129620), (1, 0, 0, 0, 108743),
    (0, 1, 1, 0, 104755), (2, 0, 0, -2, 10321), (0, 0, 1, -2, 79661),
    (0, 0, 1, 2, -34782), (4, 0, -1, 0, -23210), (0, 0, 3, 0, -21636),
    (4, 0, -2, 0, 24208), (2, 1, -1, 0, 30824), (2, 1, 0, 0, -8379),
    (1, 0, -1, 0, -16675), (1, 1, 0, 0, -12831), (2, -1, 1, 0, -10445),
    (2, 0, 2, 0, -11650), (4, 0, 0, 0, 14403),
]


def _series(table, args, E, fn):
    d, m, mp, f = args
    total = 0.0
    for kd, km, kmp, kf, coef in table:
        arg = kd * d + km * m + kmp * mp + kf * f
        factor = E ** abs(km)
        total = total + coef * factor * fn(arg)
    return total


def moon_geocentric_ecliptic(T):
    """Geocentric Moon: ecliptic lon, lat (deg, mean equinox of date), distance (km)."""
    T = np.asarray(T, dtype=float)
    Lp = 218.3164477 + 481267.88123421 * T - 0.0015786 * T**2
    D = np.radians(297.8501921 + 445267.1114034 * T - 0.0018819 * T**2)
    M = np.radians(357.5291092 + 35999.0502909 * T - 0.0001536 * T**2)
    Mp = np.radians(134.9633964 + 477198.8675055 * T + 0.0087414 * T**2)
    F = np.radians(93.2720950 + 483202.0175233 * T - 0.0036539 * T**2)
    E = 1 - 0.002516 * T - 0.0000074 * T**2
    A1 = np.radians(119.75 + 131.849 * T)
    A2 = np.radians(53.09 + 479264.290 * T)
    A3 = np.radians(313.45 + 481266.484 * T)
    Lr = np.radians(Lp)
    args = (D, M, Mp, F)

    sl = _series(_LON, args, E, np.sin)
    sl = sl + 3958 * np.sin(A1) + 1962 * np.sin(Lr - F) + 318 * np.sin(A2)
    sb = _series(_LAT, args, E, np.sin)
    sb = (
        sb - 2235 * np.sin(Lr) + 382 * np.sin(A3) + 175 * np.sin(A1 - F)
        + 175 * np.sin(A1 + F) + 127 * np.sin(Lr - Mp) - 115 * np.sin(Lr + Mp)
    )
    sr = _series(_DIST, args, E, np.cos)

    lon = (Lp + sl / 1e6) % 360.0
    lat = sb / 1e6
    dist = 385000.56 + sr / 1e3
    return lon, lat, dist


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------


def mean_obliquity_rad(T):
    return np.radians(23.439291 - 0.0130042 * np.asarray(T, dtype=float))


def ecliptic_to_j2000_equatorial(vec_ecl, T):
    """Rotate vectors from ecliptic-of-date to J2000 equatorial (ICRF-aligned)."""
    eps = mean_obliquity_rad(T)
    v = np.einsum("...ij,...j->...i", _rx(eps), vec_ecl)  # ecliptic -> equator of date
    t = np.asarray(T, dtype=float)
    arc = np.pi / 648000.0  # arcsec -> rad
    zeta = (2306.2181 * t + 0.30188 * t**2 + 0.017998 * t**3) * arc
    z = (2306.2181 * t + 1.09468 * t**2 + 0.018203 * t**3) * arc
    theta = (2004.3109 * t - 0.42665 * t**2 - 0.041833 * t**3) * arc
    # P(J2000 -> date) = Rz(z) Ry(-theta) Rz(zeta); we need its inverse.
    p_inv = np.einsum("...ij,...jk->...ik", _rz(-zeta), _ry(theta))
    p_inv = np.einsum("...ij,...jk->...ik", p_inv, _rz(-z))
    return np.einsum("...ij,...j->...i", p_inv, v)


def lunar_orientation(d):
    """IAU 2015 lunar pole (alpha0, delta0) and prime meridian W, all radians.

    d = days since J2000 (TDB ~ TT).
    """
    d = np.asarray(d, dtype=float)
    T = d / 36525.0
    E = np.radians(np.array([
        125.045 - 0.0529921 * d, 250.089 - 0.1059842 * d, 260.008 + 13.0120009 * d,
        176.625 + 13.3407154 * d, 357.529 + 0.9856003 * d, 311.589 + 26.4057084 * d,
        134.963 + 13.0649930 * d, 276.617 + 0.3287146 * d, 34.226 + 1.7484877 * d,
        15.134 - 0.1589763 * d, 119.743 + 0.0036096 * d, 239.961 + 0.1643573 * d,
        25.053 + 12.9590088 * d,
    ]))
    s = np.sin
    c = np.cos
    a0 = (269.9949 + 0.0031 * T - 3.8787 * s(E[0]) - 0.1204 * s(E[1]) + 0.0700 * s(E[2])
          - 0.0172 * s(E[3]) + 0.0072 * s(E[5]) - 0.0052 * s(E[9]) + 0.0043 * s(E[12]))
    d0 = (66.5392 + 0.0130 * T + 1.5419 * c(E[0]) + 0.0239 * c(E[1]) - 0.0278 * c(E[2])
          + 0.0068 * c(E[3]) - 0.0029 * c(E[5]) + 0.0009 * c(E[6]) + 0.0008 * c(E[9])
          - 0.0009 * c(E[12]))
    W = (38.3213 + 13.17635815 * d - 1.4e-12 * d**2 + 3.5610 * s(E[0]) + 0.1208 * s(E[1])
         - 0.0642 * s(E[2]) + 0.0158 * s(E[3]) + 0.0252 * s(E[4]) - 0.0066 * s(E[5])
         - 0.0047 * s(E[6]) - 0.0046 * s(E[7]) + 0.0028 * s(E[8]) + 0.0052 * s(E[9])
         + 0.0040 * s(E[10]) + 0.0019 * s(E[11]) - 0.0044 * s(E[12]))
    return np.radians(a0), np.radians(d0), np.radians(W % 360.0)


def icrf_to_moon_fixed(d):
    """Matrices taking J2000 equatorial vectors to the Moon body-fixed (ME) frame."""
    a0, d0, W = lunar_orientation(d)
    # passive rotation R_i(theta) == active rotation by -theta
    m = _rz(-(a0 + np.pi / 2))
    m = np.einsum("...ij,...jk->...ik", _rx(-(np.pi / 2 - d0)), m)
    m = np.einsum("...ij,...jk->...ik", _rz(-W), m)
    return m


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def _enu_basis(lat_deg, lon_deg):
    phi, lam = np.radians(lat_deg), np.radians(lon_deg)
    up = np.array([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])
    east = np.array([-np.sin(lam), np.cos(lam), 0.0])
    north = np.array([-np.sin(phi) * np.cos(lam), -np.sin(phi) * np.sin(lam), np.cos(phi)])
    return east, north, up


def _azel(vec, lat_deg, lon_deg):
    east, north, up = _enu_basis(lat_deg, lon_deg)
    v = vec / np.linalg.norm(vec, axis=-1, keepdims=True)
    el = np.degrees(np.arcsin(np.clip(v @ up, -1, 1)))
    az = np.degrees(np.arctan2(v @ east, v @ north)) % 360.0
    return az, el


def sun_earth_azel(lat_deg: float, lon_deg: float, times):
    """Azimuth/elevation (deg) of the Sun and Earth centres at a lunar site.

    Azimuth is measured from local north, clockwise through east.
    Returns dict with arrays: sun_az, sun_el, earth_az, earth_el, earth_dist_km.
    """
    jd = jd_tt(times)
    d = jd - J2000_JD
    T = d / 36525.0

    sun_lon, sun_r = sun_geocentric_ecliptic(T)
    sl = np.radians(sun_lon)
    sun_geo = (sun_r * AU_KM)[..., None] * np.stack(
        [np.cos(sl), np.sin(sl), np.zeros_like(sl)], axis=-1
    )

    mlon, mlat, mdist = moon_geocentric_ecliptic(T)
    ml, mb = np.radians(mlon), np.radians(mlat)
    moon_geo = mdist[..., None] * np.stack(
        [np.cos(mb) * np.cos(ml), np.cos(mb) * np.sin(ml), np.sin(mb)], axis=-1
    )

    sun_from_moon_ecl = sun_geo - moon_geo
    earth_from_moon_ecl = -moon_geo

    sun_eq = ecliptic_to_j2000_equatorial(sun_from_moon_ecl, T)
    earth_eq = ecliptic_to_j2000_equatorial(earth_from_moon_ecl, T)

    rot = icrf_to_moon_fixed(d)
    sun_bf = np.einsum("...ij,...j->...i", rot, sun_eq)
    earth_bf = np.einsum("...ij,...j->...i", rot, earth_eq)

    east, north, up = _enu_basis(lat_deg, lon_deg)
    site = R_MOON_KM * up
    earth_topo = earth_bf - site  # parallax: Earth is close
    sun_topo = sun_bf - site * 0.0  # Sun parallax from site is negligible

    s_az, s_el = _azel(sun_topo, lat_deg, lon_deg)
    e_az, e_el = _azel(earth_topo, lat_deg, lon_deg)
    return {
        "sun_az": s_az, "sun_el": s_el,
        "earth_az": e_az, "earth_el": e_el,
        "earth_dist_km": np.linalg.norm(earth_topo, axis=-1),
    }


def sub_earth_and_solar_points(times):
    """Sub-Earth and sub-solar selenographic (lat, lon) in degrees, for validation."""
    jd = jd_tt(times)
    d = jd - J2000_JD
    T = d / 36525.0
    sun_lon, sun_r = sun_geocentric_ecliptic(T)
    sl = np.radians(sun_lon)
    sun_geo = (sun_r * AU_KM)[..., None] * np.stack([np.cos(sl), np.sin(sl), np.zeros_like(sl)], -1)
    mlon, mlat, mdist = moon_geocentric_ecliptic(T)
    ml, mb = np.radians(mlon), np.radians(mlat)
    moon_geo = mdist[..., None] * np.stack(
        [np.cos(mb) * np.cos(ml), np.cos(mb) * np.sin(ml), np.sin(mb)], -1)
    rot = icrf_to_moon_fixed(d)

    def ll(v_ecl):
        v = np.einsum("...ij,...j->...i", rot, ecliptic_to_j2000_equatorial(v_ecl, T))
        v = v / np.linalg.norm(v, axis=-1, keepdims=True)
        return np.degrees(np.arcsin(v[..., 2])), np.degrees(np.arctan2(v[..., 1], v[..., 0]))

    earth_lat, earth_lon = ll(-moon_geo)
    sun_lat, sun_lon_bf = ll(sun_geo - moon_geo)
    earth_lon = (earth_lon + 180) % 360 - 180
    return {"earth_lat": earth_lat, "earth_lon": earth_lon, "sun_lat": sun_lat, "sun_lon": sun_lon_bf}


def default_spice_kernels() -> list[str]:
    """The DE440 kernel set this project expects, in `backend/data/spice/`."""
    return [str(SPICE_KERNEL_DIR / name) for name in SPICE_KERNEL_FILES]


def load_spice_kernels(kernels) -> tuple[str, ...]:
    """Furnish a SPICE kernel set once per process and return resolved paths.

    SPICE's kernel pool is process-wide. If a different set is requested, the
    old pool is cleared first. Missing files fail loudly instead of leaving a
    half-configured backend.
    """
    global _SPICE_LOADED
    import spiceypy as sp

    paths = tuple(str(Path(k).expanduser().resolve()) for k in kernels)
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError("missing SPICE kernel(s): " + ", ".join(missing))
    if _SPICE_LOADED == paths:
        return paths
    if _SPICE_LOADED is not None:
        sp.kclear()
    for p in paths:
        sp.furnsh(p)
    _SPICE_LOADED = paths
    return paths


def spice_backend(lat_deg, lon_deg, times, kernels=None):
    """Sun/Earth az/el and Earth distance from SPICE DE440, in the MOON_ME frame.

    `kernels` furnishes a kernel set (cached process-wide). If omitted, a set
    must already have been loaded with `load_spice_kernels`. The site is placed
    on the reference sphere; elevation changes these directions by well under
    0.001 deg.
    """
    import spiceypy as sp

    if kernels is not None:
        load_spice_kernels(kernels)
    elif _SPICE_LOADED is None:
        raise RuntimeError("no SPICE kernels loaded; pass kernels or call load_spice_kernels()")

    t = np.asarray(times).astype("datetime64[s]")
    ets = [sp.str2et(str(x)) for x in t]
    phi, lam = np.radians(lat_deg), np.radians(lon_deg)
    site = sp.georec(lam, phi, 0.0, R_MOON_KM, 0.0)
    out = {k: [] for k in ("sun_az", "sun_el", "earth_az", "earth_el", "earth_dist_km")}
    for et in ets:
        for body, key in (("SUN", "sun"), ("EARTH", "earth")):
            st, _ = sp.spkpos(body, et, "MOON_ME", "LT+S", "MOON")
            v = np.asarray(st, dtype=float) - site
            az, el = _azel(v, lat_deg, lon_deg)
            out[key + "_az"].append(float(az))
            out[key + "_el"].append(float(el))
            if key == "earth":
                out["earth_dist_km"].append(float(np.linalg.norm(v)))
    return {k: np.asarray(v, dtype=float) for k, v in out.items()}
