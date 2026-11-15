import numpy as np
import pytest

from backend.dem import DEM, R_MOON_M, synthetic_dem
from backend.height_sweep import height_sweep
from backend.horizon import compute_horizon, horizon_at
from backend.uncertainty import mc_visibility, window_uncertainty
from backend.visibility import BOTH, COMMS_ONLY, POWER_ONLY, classify, longest_run, metrics
from backend.windows import find_windows

SITE_LAT, SITE_LON = -89.5, 0.0   # lon 0 -> east is +y in the projection plane


def wall_dem(height_m, dist_m, size=401, px=100.0):
    """Flat DEM with a 2-row wall `dist_m` east of the site (site at x = rho, y = 0)."""
    z = np.zeros((size, size), dtype=np.float32)
    c = size // 2
    wall_row = c - int(round(dist_m / px))
    z[wall_row - 1: wall_row + 1, :] = height_m
    return DEM(z, px, float(c), float(c), synthetic=True, label="test wall")


def test_projection_roundtrip():
    lat, lon = -89.3, 211.0
    x, y = DEM.project(lat, lon)
    lat2, lon2 = DEM.unproject(x, y)
    assert abs(lat2 - lat) < 1e-9 and abs(lon2 - lon) < 1e-9


def test_projection_scale_near_pole():
    # 1 degree of colatitude is ~30.3 km
    x, y = DEM.project(-89.0, 0.0)
    assert abs(np.hypot(x, y) - R_MOON_M * np.radians(1.0)) < 100


def test_flat_terrain_horizon_is_level():
    z = np.zeros((401, 401), dtype=np.float32)
    dem = DEM(z, 100.0, 200.0, 200.0)
    az, hor = compute_horizon(dem, SITE_LAT, SITE_LON)
    assert np.max(np.abs(hor)) < 0.01


def test_wall_appears_at_east_with_correct_angle():
    H, D = 300.0, 3000.0
    dem = wall_dem(H, D)
    az, hor = compute_horizon(dem, SITE_LAT, SITE_LON, rmax_m=20000)
    expected = np.degrees(np.arctan2(H - D**2 / (2 * R_MOON_M), D))   # ~5.7 deg
    assert abs(hor[90] - expected) < 0.3
    assert abs(hor[270]) < 0.05           # nothing to the west
    assert np.argmax(hor) in range(85, 96)
    assert hor[0] < expected - 1.0        # north is lower than east


def test_observer_height_lowers_horizon():
    dem = wall_dem(300.0, 3000.0)
    _, h0 = compute_horizon(dem, SITE_LAT, SITE_LON, 0.0, 20000)
    _, h10 = compute_horizon(dem, SITE_LAT, SITE_LON, 10.0, 20000)
    assert h10[90] < h0[90]


def test_horizon_at_periodic():
    az = np.arange(0, 360, 1.0)
    hor = np.where(az == 359, 4.0, 0.0)
    assert horizon_at(az, hor, 359.5) == pytest.approx(2.0)
    assert horizon_at(az, hor, 0.0) == pytest.approx(0.0)


def test_classify_codes():
    az = np.arange(0, 360, 1.0)
    hor = np.full(360, 2.0)
    c = classify([10, 10], [1.0, 3.0], [200, 200], [3.0, 1.0], az, hor)
    assert list(c["code"]) == [COMMS_ONLY, POWER_ONLY]
    c2 = classify([10], [3.0], [200], [3.0], az, hor)
    assert c2["code"][0] == BOTH
    c3 = classify([10], [2.5], [200], [2.5], az, hor, sun_margin_deg=1.0)
    assert c3["power"][0] == False and c3["comms"][0] == True  # noqa: E712


def test_longest_run_and_metrics():
    assert longest_run(np.array([0, 1, 1, 0, 1, 1, 1], dtype=bool)) == 3
    assert longest_run(np.zeros(5, dtype=bool)) == 0
    p = np.array([1, 1, 0, 0, 1, 1, 1, 0], dtype=bool)
    c = np.array([0, 1, 1, 0, 0, 1, 1, 0], dtype=bool)
    m = metrics(p, c, step_h=2.0)
    assert m["power_pct"] == pytest.approx(62.5)
    assert m["comms_pct"] == pytest.approx(50.0)
    assert m["both_pct"] == pytest.approx(37.5)
    assert m["longest_dark_h"] == 4.0           # two dark samples x 2 h
    assert m["longest_comms_gap_h"] == 4.0      # samples 3-4 are a 2-sample gap


def _series(n=200):
    power = np.zeros(n, dtype=bool)
    comms = np.zeros(n, dtype=bool)
    power[0:150] = True
    comms[100:150] = True
    times = np.datetime64("2026-11-14T00:00") + np.arange(n) * np.timedelta64(1, "h")
    return times, power, comms


def test_window_finder_picks_the_overlap():
    times, power, comms = _series()
    res = find_windows(times, power, comms, duration_h=48, objective="balanced", top_n=1)
    w = res[0]
    assert 100 <= w["start_index"] <= 102
    assert w["metrics"]["both_pct"] == pytest.approx(100.0)


def test_window_finder_battery_constraint():
    times, power, comms = _series()
    ok = find_windows(times, power, comms, duration_h=48, objective="survive", battery_h=10, top_n=1)
    assert ok[0]["feasible"] and ok[0]["metrics"]["longest_dark_h"] <= 10
    dark = np.zeros(200, dtype=bool)
    bad = find_windows(times, dark, dark, duration_h=48, objective="survive", battery_h=10, top_n=3)
    assert all(not w["feasible"] for w in bad)


def test_window_finder_results_do_not_overlap_and_match_brute_force():
    rng = np.random.default_rng(3)
    n = 300
    power = rng.random(n) > 0.4
    comms = rng.random(n) > 0.5
    times = np.datetime64("2026-11-14T00:00") + np.arange(n) * np.timedelta64(1, "h")
    res = find_windows(times, power, comms, duration_h=24, top_n=4)
    starts = sorted(w["start_index"] for w in res)
    assert all(b - a >= 24 for a, b in zip(starts, starts[1:]))
    for w in res:  # fast metrics must equal brute force on the same slice
        s, e = w["start_index"], w["end_index"]
        bf = metrics(power[s:e], comms[s:e])
        for k in ("power_pct", "comms_pct", "both_pct", "longest_dark_h", "longest_comms_gap_h"):
            assert w["metrics"][k] == pytest.approx(bf[k])


def test_height_sweep_finds_the_flip():
    # 12 m wall 300 m east -> blocks a 2.05 deg Sun at heights 0-1 m, clears from 2 m
    dem = wall_dem(12.0, 300.0)
    n = 24
    series = {"sun_az": np.full(n, 90.0), "sun_el": np.full(n, 2.05),
              "earth_az": np.full(n, 270.0), "earth_el": np.full(n, 10.0)}
    out = height_sweep(dem, SITE_LAT, SITE_LON, series, heights=(0, 1, 2, 3), rmax_m=5000)
    p = [r["power_pct"] for r in out["rows"]]
    assert p == [0.0, 0.0, 100.0, 100.0]
    j = out["biggest_jumps"]["power_pct"]
    assert j["is_flip"] and j["from_height_m"] == 1.0 and j["to_height_m"] == 2.0
    assert not out["biggest_jumps"]["comms_pct"]["is_flip"]


def test_uncertainty_labels():
    dem = wall_dem(12.0, 300.0)
    n = 24
    easy = {"sun_az": np.full(n, 90.0), "sun_el": np.full(n, 10.0),
            "earth_az": np.full(n, 270.0), "earth_el": np.full(n, 10.0)}
    mc = mc_visibility(dem, SITE_LAT, SITE_LON, easy, n=20, sigma_m=8.0, corr_m=300.0, rmax_m=5000)
    assert mc["power"].shape == (20, n)
    assert window_uncertainty(mc, 0, n)["robustness"] == "robust"

    # Sun sitting right at the wall's top edge: outcome flips between realizations
    edge_el = np.degrees(np.arctan2(12.0, 300.0))
    hard = dict(easy, sun_el=np.full(n, edge_el))
    mc2 = mc_visibility(dem, SITE_LAT, SITE_LON, hard, n=30, sigma_m=8.0, corr_m=300.0, rmax_m=5000)
    assert window_uncertainty(mc2, 0, n)["robustness"] != "robust"


def test_synthetic_dem_is_labelled():
    dem = synthetic_dem(size_px=200, px_m=500.0)
    assert dem.synthetic and "SYNTHETIC" in dem.label


def test_proj_south_polar_conversion_matches_projection_math():
    """Build the same smooth field on a PROJ-style grid and on our grid; conversion must agree."""
    from backend.dem import from_proj_south_polar

    n, px = 301, 1000.0
    c = (n - 1) / 2
    rr, cc = np.mgrid[0:n, 0:n].astype(float)
    R = R_MOON_M

    def field(lat_deg, lon_deg):  # smooth, asymmetric in lon so a rotation/mirror would show
        lat, lon = np.radians(lat_deg), np.radians(lon_deg)
        return 1000.0 * np.cos(lon - 0.7) * np.sin(2 * (lat + np.pi / 2) * 20) + 500.0 * np.sin(2 * lon)

    # PROJ-style grid: x = rho*sin(lon), y = rho*cos(lon); col = c + x/px, row = c - y/px
    x_s, y_s = (cc - c) * px, (c - rr) * px
    rho_s = np.hypot(x_s, y_s)
    lon_s = np.degrees(np.arctan2(x_s, y_s)) % 360
    lat_s = np.degrees(2 * np.arctan(rho_s / (2 * R)) - np.pi / 2)
    z_std = field(lat_s, lon_s)

    dem = from_proj_south_polar(z_std, px)
    # our grid: x = rho*cos(lon), y = rho*sin(lon); col = cx + x/px, row = cy - y/px
    x_m, y_m = (cc - dem.cx) * px, (dem.cy - rr) * px
    lon_m = np.degrees(np.arctan2(y_m, x_m)) % 360
    lat_m = np.degrees(2 * np.arctan(np.hypot(x_m, y_m) / (2 * R)) - np.pi / 2)
    expected = field(lat_m, lon_m)
    inner = np.hypot(x_m, y_m) < 100_000   # away from the singular pole pixel and corners
    assert np.allclose(dem.z[inner], expected[inner], atol=1e-3 * 1500)
    # and sampling by lat/lon through the DEM API recovers the field
    for lat, lon in [(-89.5, 30.0), (-89.2, 200.0), (-88.9, 310.0)]:
        got = dem.sample_latlon(lat, lon)[0]
        assert abs(got - field(np.array(lat), np.array(lon))) < 25.0


def test_proj_conversion_rejects_bad_shapes():
    from backend.dem import from_proj_south_polar
    with pytest.raises(ValueError):
        from_proj_south_polar(np.zeros((100, 100)), 100.0)
    with pytest.raises(ValueError):
        from_proj_south_polar(np.zeros((101, 99)), 100.0)
