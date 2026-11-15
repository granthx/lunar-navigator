#!/usr/bin/env python3
"""Turn a real south-polar elevation GeoTIFF into the .npz the navigator loads.

NOT RUN in the development sandbox (no data access). Read scripts/README_DATA.md first;
orientation mistakes silently rotate or mirror every horizon.

    pip install rasterio numpy
    python scripts/prepare_dem.py LDEM_80S_xxx.tif backend/data/dem.npz --radius-km 60 --convention proj
    LUNAR_DEM=backend/data/dem.npz python -m uvicorn backend.api.server:app

--convention proj      source is in the common PROJ south-polar orientation
                       (x = rho*sin(lon), y = rho*cos(lon)); the array is converted.
--convention internal  source already uses x = rho*cos(lon), y = rho*sin(lon); no conversion.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.dem import DEM, from_proj_south_polar  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tif")
    ap.add_argument("out")
    ap.add_argument("--radius-km", type=float, default=60.0, help="crop radius around the pole")
    ap.add_argument("--convention", choices=["proj", "internal"], required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    try:
        import rasterio
    except ImportError:
        print("This script needs rasterio:  pip install rasterio", file=sys.stderr)
        return 2

    with rasterio.open(a.tif) as src:
        t = src.transform
        px_x, px_y = abs(t.a), abs(t.e)
        if abs(px_x - px_y) > 1e-6 * px_x:
            print("Non-square pixels are not supported.", file=sys.stderr)
            return 2
        unit = (src.crs.linear_units if src.crs else "unknown")
        print(f"CRS: {src.crs}\npixel size: {px_x} ({unit})\nshape: {src.shape}")
        if "metre" not in str(unit).lower() and "meter" not in str(unit).lower():
            print("Warning: linear units are not metres; check the file before trusting results.", file=sys.stderr)
        # pole = projected origin (0, 0)
        col_f, row_f = ~t * (0.0, 0.0)
        col, row = int(round(col_f)), int(round(row_f))
        if abs(col_f - col) > 0.5 or abs(row_f - row) > 0.5:
            print("Pole is outside the pixel grid", file=sys.stderr)
            return 2
        r = int(a.radius_km * 1000 / px_x)
        r0, r1, c0, c1 = row - r, row + r + 1, col - r, col + r + 1
        if r0 < 0 or c0 < 0 or r1 > src.height or c1 > src.width:
            print("Crop radius extends beyond the file; use a smaller --radius-km.", file=sys.stderr)
            return 2
        from rasterio.windows import Window
        z = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float32)
        if src.nodata is not None:
            z[z == src.nodata] = np.nan

    label = a.label or f"{Path(a.tif).name} (crop {a.radius_km:g} km)"
    if a.convention == "proj":
        dem = from_proj_south_polar(z, px_x, label)
    else:
        c = (z.shape[0] - 1) / 2.0
        dem = DEM(z, px_x, c, c, synthetic=False, label=label)
    dem.to_npz(a.out)
    print(f"wrote {a.out}: {dem.z.shape}, elevation {np.nanmin(dem.z):.0f} to {np.nanmax(dem.z):.0f} m")
    print("NEXT: verify orientation with landmarks (scripts/README_DATA.md) before trusting any result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
