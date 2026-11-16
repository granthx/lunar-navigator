#!/usr/bin/env python3
"""Turn a real south-polar elevation GeoTIFF into the .npz the navigator loads.

Read scripts/README_DATA.md first; orientation mistakes silently rotate or mirror
every horizon.

    pip install rasterio numpy
    python scripts/prepare_dem.py LDEM_80S_xxx.tif backend/data/dem.npz --radius-km 240 --convention proj
    LUNAR_DEM=backend/data/dem.npz python -m uvicorn backend.api.server:app

--convention proj      source is in the common PROJ south-polar orientation
                       (x = rho*sin(lon), y = rho*cos(lon)). The pole may sit at a
                       pixel centre (odd grid) or between four pixels (even grid);
                       the area-aware converter handles both.
--convention internal  source already uses x = rho*cos(lon), y = rho*sin(lon)
                       with the pole at a pixel centre; no conversion.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.dem import DEM, from_proj_south_polar_area  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tif")
    ap.add_argument("out")
    ap.add_argument("--radius-km", type=float, default=60.0,
                    help="crop radius around the pole (the current Artemis III regions need about 220 km)")
    ap.add_argument("--convention", choices=["proj", "internal"], required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    if a.radius_km <= 0:
        print("--radius-km must be positive", file=sys.stderr)
        return 2

    try:
        import rasterio
        from rasterio.windows import Window
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
        # The projected origin in continuous pixel coordinates. Rasterio maps pixel
        # corners; scipy's map_coordinates uses centres, hence the half-pixel shift.
        col_f, row_f = ~t * (0.0, 0.0)
        pole_col, pole_row = col_f - 0.5, row_f - 0.5
        print(f"pole at continuous pixel ({pole_col:.3f}, {pole_row:.3f})")
        label = a.label or f"{Path(a.tif).name} (crop {a.radius_km:g} km, {px_x:g} m/px)"

        if a.convention == "proj":
            z = src.read(1).astype(np.float32)
            if src.nodata is not None:
                z[z == src.nodata] = np.nan
            try:
                dem = from_proj_south_polar_area(z, px_x, pole_col, pole_row,
                                                 a.radius_km * 1000.0, label)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        else:
            if abs(pole_col - round(pole_col)) > 1e-6 or abs(pole_row - round(pole_row)) > 1e-6:
                print("The 'internal' convention needs the pole at a pixel centre; "
                      "use 'proj' for an area-registered grid.", file=sys.stderr)
                return 2
            col, row = int(round(pole_col)), int(round(pole_row))
            r = int(a.radius_km * 1000 / px_x)
            r0, r1, c0, c1 = row - r, row + r + 1, col - r, col + r + 1
            if r0 < 0 or c0 < 0 or r1 > src.height or c1 > src.width:
                print("Crop radius extends beyond the file; use a smaller --radius-km.", file=sys.stderr)
                return 2
            z = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float32)
            if src.nodata is not None:
                z[z == src.nodata] = np.nan
            c = (z.shape[0] - 1) / 2.0
            dem = DEM(z, px_x, c, c, synthetic=False, label=label)

    dem.to_npz(a.out)
    print(f"wrote {a.out}: {dem.z.shape}, radius {dem.radius_m / 1000:.1f} km, "
          f"elevation {np.nanmin(dem.z):.0f} to {np.nanmax(dem.z):.0f} m")
    print("NEXT: verify orientation with landmarks (scripts/README_DATA.md) before trusting any result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
