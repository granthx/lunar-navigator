"""Digital elevation model in south-polar stereographic projection.

Real data: LOLA south-polar DEM products (e.g. 20-80 m/pixel) use a polar
stereographic projection centred on the pole. `DEM.from_npz` loads a crop that
has been converted to a numpy file (see scripts/README_DATA.md).

Synthetic data: `synthetic_dem()` builds a clearly labelled stand-in terrain so
the full pipeline can be developed and demonstrated offline. IT IS NOT REAL
LUNAR TERRAIN and must never be presented as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

R_MOON_M = 1_737_400.0


@dataclass
class DEM:
    z: np.ndarray                # elevation (m) above the 1737.4 km reference sphere
    px_m: float                  # pixel size (m)
    cx: float                    # column of the south pole (pixel coords)
    cy: float                    # row of the south pole
    synthetic: bool = False
    label: str = ""
    meta: dict = field(default_factory=dict)

    # -- projection -------------------------------------------------------
    @staticmethod
    def project(lat_deg, lon_deg):
        """Selenographic (lat, lon) -> polar stereographic (x, y) metres. South pole = origin."""
        lat = np.radians(lat_deg)
        lon = np.radians(lon_deg)
        rho = 2.0 * R_MOON_M * np.tan(np.pi / 4.0 + lat / 2.0)
        return rho * np.cos(lon), rho * np.sin(lon)

    @staticmethod
    def unproject(x, y):
        """Polar stereographic (x, y) metres -> selenographic (lat, lon) degrees."""
        rho = np.hypot(x, y)
        lat = 2.0 * np.arctan(rho / (2.0 * R_MOON_M)) - np.pi / 2.0
        lon = np.arctan2(y, x) % (2 * np.pi)
        return np.degrees(lat), np.degrees(lon)

    def to_pixels(self, x, y):
        return self.cx + x / self.px_m, self.cy - y / self.px_m   # (col, row)

    def sample_latlon(self, lat_deg, lon_deg):
        x, y = self.project(lat_deg, lon_deg)
        col, row = self.to_pixels(x, y)
        return map_coordinates(self.z, [np.atleast_1d(row), np.atleast_1d(col)],
                               order=1, mode="constant", cval=np.nan)

    @property
    def radius_m(self) -> float:
        """Distance from the pole to the nearest DEM edge."""
        return min(self.cx, self.cy, self.z.shape[1] - 1 - self.cx, self.z.shape[0] - 1 - self.cy) * self.px_m

    # -- io ---------------------------------------------------------------
    @classmethod
    def from_npz(cls, path: str) -> "DEM":
        d = np.load(path, allow_pickle=False)
        return cls(z=d["z"].astype(np.float32), px_m=float(d["px_m"]),
                   cx=float(d["cx"]), cy=float(d["cy"]),
                   synthetic=False, label=str(d["label"]) if "label" in d else path)

    def to_npz(self, path: str) -> None:
        np.savez_compressed(path, z=self.z, px_m=self.px_m, cx=self.cx, cy=self.cy,
                            label=self.label)

    def crop_around_latlon(self, lat_deg, lon_deg, radius_m) -> "DEM":
        """Sub-DEM covering `radius_m` around a site (keeps projection geometry)."""
        x, y = self.project(lat_deg, lon_deg)
        col, row = self.to_pixels(x, y)
        r = int(np.ceil(radius_m / self.px_m)) + 2
        c0, c1 = max(0, int(col) - r), min(self.z.shape[1], int(col) + r + 1)
        r0, r1 = max(0, int(row) - r), min(self.z.shape[0], int(row) + r + 1)
        return DEM(self.z[r0:r1, c0:c1], self.px_m, self.cx - c0, self.cy - r0,
                   self.synthetic, self.label, self.meta)

    def perturbed(self, sigma_m: float, corr_px: float, rng: np.random.Generator) -> "DEM":
        """Copy with spatially correlated vertical noise (for uncertainty analysis)."""
        noise = gaussian_filter(rng.standard_normal(self.z.shape), corr_px, mode="reflect")
        std = noise.std()
        if std > 0:
            noise *= sigma_m / std
        return DEM(self.z + noise.astype(self.z.dtype), self.px_m, self.cx, self.cy,
                   self.synthetic, self.label, self.meta)


def from_proj_south_polar(z_std: np.ndarray, px_m: float, label: str = "") -> DEM:
    """Convert an array in the common PROJ south-polar-stereographic orientation to this
    project's internal grid convention (x = rho*cos(lon), y = rho*sin(lon)).

    ASSUMPTION (verify against your data product): the source grid has the pole at the exact
    centre of a square array, columns increasing with x = rho*sin(lon), rows increasing with
    -y where y = rho*cos(lon), and longitude is east-positive. Under that assumption the two
    grids differ by a flip of both axes plus a transpose. If your product uses another
    convention, horizons will be rotated or mirrored, so ALWAYS check a few landmarks
    (see scripts/README_DATA.md).
    """
    z_std = np.asarray(z_std)
    if z_std.ndim != 2 or z_std.shape[0] != z_std.shape[1] or z_std.shape[0] % 2 == 0:
        raise ValueError("expected a square array with an odd side length, pole at the centre")
    z = np.ascontiguousarray(z_std[::-1, ::-1].T).astype(np.float32)
    c = (z.shape[0] - 1) / 2.0
    return DEM(z, px_m, c, c, synthetic=False, label=label or "converted from PROJ south polar grid")


def synthetic_dem(size_px: int = 1000, px_m: float = 100.0, seed: int = 7) -> DEM:
    """Fractal terrain + craters + massifs, centred on the south pole. NOT REAL DATA."""
    rng = np.random.default_rng(seed)
    n = size_px
    # fractal base via spectral synthesis
    kx = np.fft.fftfreq(n)[:, None]
    ky = np.fft.fftfreq(n)[None, :]
    k = np.sqrt(kx**2 + ky**2)
    k[0, 0] = 1.0
    spec = (rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))) * k ** (-1.6)
    spec[0, 0] = 0
    base = np.real(np.fft.ifft2(spec))
    base = base / base.std() * 70.0

    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    xm = (xx - (n - 1) / 2) * px_m
    ym = ((n - 1) / 2 - yy) * px_m
    z = base

    # craters
    for _ in range(9):
        rad = rng.uniform(2000, 11000)
        cxm, cym = rng.uniform(-45000, 45000, size=2)
        r = np.hypot(xm - cxm, ym - cym) / rad
        depth = 0.09 * 2 * rad
        bowl = -depth * (1 - np.clip(r, 0, 1) ** 2)
        rim = 0.03 * 2 * rad * np.exp(-((r - 1.0) / 0.18) ** 2)
        z = z + np.where(r < 1.0, bowl, 0.0) + rim

    # massifs and a long ridge so sites differ visibly
    for _ in range(7):
        w = rng.uniform(2500, 6500)
        h = rng.uniform(500, 1600)
        cxm, cym = rng.uniform(-40000, 40000, size=2)
        z = z + h * np.exp(-((xm - cxm) ** 2 + (ym - cym) ** 2) / (2 * w**2))
    ang = rng.uniform(0, np.pi)
    d = (xm - 8000) * np.cos(ang) + (ym + 5000) * np.sin(ang)
    along = -(xm - 8000) * np.sin(ang) + (ym + 5000) * np.cos(ang)
    z = z + 900 * np.exp(-(d / 900) ** 2) * np.exp(-(along / 14000) ** 2)

    z = gaussian_filter(z, 1.0)
    return DEM(z.astype(np.float32), px_m, (n - 1) / 2, (n - 1) / 2, synthetic=True,
               label="SYNTHETIC demo terrain (not real lunar data)",
               meta={"seed": seed})
