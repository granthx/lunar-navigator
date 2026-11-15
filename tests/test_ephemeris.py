import numpy as np

from backend import ephemeris as eph


def test_meeus_moon_example_47a():
    # Meeus, Astronomical Algorithms, example 47.a: 1992 April 12, 0h TD
    T = (2448724.5 - 2451545.0) / 36525.0
    lon, lat, dist = eph.moon_geocentric_ecliptic(np.array([T]))
    assert abs(lon[0] - 133.162655) < 0.02
    assert abs(lat[0] - (-3.229126)) < 0.02
    assert abs(dist[0] - 368409.7) < 500


def test_meeus_sun_example_25a():
    # Example 25.a: 1992 October 13, 0h TD. Apparent longitude ~199.909 deg, R ~0.99766 AU
    T = (2448908.5 - 2451545.0) / 36525.0
    lon, R = eph.sun_geocentric_ecliptic(np.array([T]))
    assert abs(lon[0] - 199.909) < 0.01
    assert abs(R[0] - 0.99766) < 0.0005


def test_moon_pole_maps_to_z_axis():
    d = np.array([0.0, 3000.0, 9800.0])
    a0, d0, _ = eph.lunar_orientation(d)
    pole = np.stack([np.cos(d0) * np.cos(a0), np.cos(d0) * np.sin(a0), np.sin(d0)], -1)
    rot = eph.icrf_to_moon_fixed(d)
    out = np.einsum("...ij,...j->...i", rot, pole)
    assert np.allclose(out, [0, 0, 1], atol=1e-9)


def test_rotation_matrices_orthonormal():
    d = np.linspace(0, 9000, 7)
    rot = eph.icrf_to_moon_fixed(d)
    for m in rot:
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-10)
        assert abs(np.linalg.det(m) - 1) < 1e-10


def test_precession_magnitude():
    # ~26.8 years since J2000: equinox shift should be ~0.37 deg
    T = np.array([0.268])
    v = eph.ecliptic_to_j2000_equatorial(np.array([[1.0, 0.0, 0.0]]), T)[0]
    angle = np.degrees(np.arccos(np.clip(v[0], -1, 1)))
    assert 0.30 < angle < 0.45


def _year_of_hours(start="2026-11-14T00:00"):
    t0 = np.datetime64(start)
    return t0 + np.arange(0, 24 * 365) * np.timedelta64(1, "h")


def test_sub_earth_point_stays_within_libration_limits():
    p = eph.sub_earth_and_solar_points(_year_of_hours())
    # optical + physical libration: |lat| <~ 7 deg, |lon| <~ 8 deg
    assert np.max(np.abs(p["earth_lat"])) < 7.6
    assert np.max(np.abs(p["earth_lon"])) < 9.0
    assert np.max(np.abs(p["earth_lat"])) > 5.0  # must actually librate
    assert np.max(np.abs(p["earth_lon"])) > 5.0


def test_subsolar_latitude_bounded_by_lunar_obliquity():
    p = eph.sub_earth_and_solar_points(_year_of_hours())
    assert np.max(np.abs(p["sun_lat"])) < 1.7
    assert np.max(np.abs(p["sun_lat"])) > 1.2


def test_sun_elevation_at_south_pole_small():
    times = _year_of_hours()
    r = eph.sun_earth_azel(-89.99, 0.0, times)
    assert np.max(r["sun_el"]) < 1.8
    assert np.min(r["sun_el"]) > -1.8
    # Sun spends roughly half the time above the horizon at the pole
    frac = np.mean(r["sun_el"] > 0)
    assert 0.35 < frac < 0.65


def test_earth_elevation_at_south_pole_follows_libration_period():
    times = np.datetime64("2026-11-14T00:00") + np.arange(0, 24 * 60) * np.timedelta64(1, "h")
    r = eph.sun_earth_azel(-89.99, 0.0, times)
    el = r["earth_el"]
    assert np.max(el) < 7.6 and np.min(el) > -7.6
    # sign changes: Earth rises and sets with ~27.3-day (draconic) libration
    crossings = np.sum(np.diff(np.sign(el)) != 0)
    assert 3 <= crossings <= 6  # ~2 months -> ~2 sets of rise+set


def test_earth_not_visible_from_far_side():
    times = np.datetime64("2026-11-14T00:00") + np.arange(0, 24 * 30) * np.timedelta64(1, "h")
    r = eph.sun_earth_azel(0.0, 180.0, times)
    assert np.max(r["earth_el"]) < 0
    # and Earth is near zenith from the sub-Earth point
    r2 = eph.sun_earth_azel(0.0, 0.0, times)
    assert np.max(r2["earth_el"]) > 80


def test_earth_distance_range():
    r = eph.sun_earth_azel(-89.5, 30.0, _year_of_hours())
    assert 350000 < np.min(r["earth_dist_km"]) < 375000
    assert 395000 < np.max(r["earth_dist_km"]) < 410000
