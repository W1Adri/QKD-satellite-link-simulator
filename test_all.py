"""
Comprehensive test suite for QKD Satellite Link Simulator.
Tests all physics modules, services, and API endpoints.
"""
import sys
import math
import traceback
from datetime import datetime, timezone, timedelta

# Track results
PASS = 0
FAIL = 0
ERRORS = []

def test(name, func):
    global PASS, FAIL
    try:
        func()
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        err_msg = f"  [FAIL] {name}: {e}"
        print(err_msg)
        traceback.print_exc()
        ERRORS.append((name, str(e), traceback.format_exc()))

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ========================================================================
# 1. PHYSICS: CONSTANTS
# ========================================================================
section("1. Physics: Constants")

def test_constants_import():
    from app.physics.constants import (
        MU_EARTH, EARTH_RADIUS_KM, EARTH_ROT_RATE, J2, J3, J4,
        SIDEREAL_DAY, DEG2RAD, RAD2DEG, C_LIGHT_KMS, C_LIGHT_MS,
        H_PLANCK, SOLAR_MEAN_MOTION, MIN_ALTITUDE_KM, GEO_ALTITUDE_KM,
        MIN_SEMI_MAJOR, MAX_SEMI_MAJOR,
    )
    assert MU_EARTH > 0
    assert EARTH_RADIUS_KM > 6000
    assert abs(DEG2RAD * RAD2DEG - 1.0) < 1e-12
    assert MIN_SEMI_MAJOR < MAX_SEMI_MAJOR

test("constants import and basic values", test_constants_import)


# ========================================================================
# 2. PHYSICS: KEPLER
# ========================================================================
section("2. Physics: Kepler Equation Solver")

def test_kepler_solve():
    from app.physics.kepler import solve_kepler
    # Circular orbit: M = E
    E = solve_kepler(1.0, 0.0)
    assert abs(E - 1.0) < 1e-6, f"E={E}, expected 1.0"

def test_kepler_eccentric():
    from app.physics.kepler import solve_kepler
    E = solve_kepler(math.pi, 0.5)
    # Verify: M = E - e*sin(E)
    M_check = E - 0.5 * math.sin(E)
    assert abs(M_check - math.pi) < 1e-6, f"M_check={M_check}"

def test_orbital_position():
    from app.physics.kepler import orbital_position
    r_eci, nu, r = orbital_position(7000.0, 0.001, 0.5, 0.0, 0.0, 0.0)
    assert len(r_eci) == 3
    assert r > 0
    assert abs(r - 7000.0) < 100  # roughly correct radius

def test_orbital_position_velocity():
    from app.physics.kepler import orbital_position_velocity
    r, v, nu, n, radius = orbital_position_velocity(7000.0, 0.001, 0.5, 0.0, 0.0, 0.0)
    assert len(r) == 3
    assert len(v) == 3
    assert n > 0
    # Velocity should be ~7.5 km/s for LEO
    v_mag = math.sqrt(sum(c*c for c in v))
    assert 5.0 < v_mag < 10.0, f"v_mag={v_mag}"

test("solve_kepler (circular)", test_kepler_solve)
test("solve_kepler (eccentric)", test_kepler_eccentric)
test("orbital_position", test_orbital_position)
test("orbital_position_velocity", test_orbital_position_velocity)


# ========================================================================
# 3. PHYSICS: PROPAGATION
# ========================================================================
section("3. Physics: Orbit Propagation")

def test_j2_secular_rates():
    from app.physics.propagation import compute_j2_secular_rates
    rates = compute_j2_secular_rates(7000.0, 0.001, math.radians(53.0))
    assert rates.mean_motion > 0
    assert rates.dot_raan != 0  # J2 should cause RAAN precession

def test_enhanced_secular_rates():
    from app.physics.propagation import compute_enhanced_secular_rates
    rates = compute_enhanced_secular_rates(7000.0, 0.001, math.radians(53.0), True, True)
    assert rates.mean_motion > 0

def test_date_to_julian():
    from app.physics.propagation import date_to_julian
    dt = datetime(2000, 1, 1, 12, 0, 0)
    jd = date_to_julian(dt)
    assert abs(jd - 2451545.0) < 0.01, f"JD={jd}"

def test_gmst():
    from app.physics.propagation import gmst_from_date
    dt = datetime(2000, 1, 1, 12, 0, 0)
    gmst = gmst_from_date(dt)
    assert 0 <= gmst < 2 * math.pi

def test_ecef_latlon():
    from app.physics.propagation import ecef_to_latlon, ecef_from_latlon
    # On equator at prime meridian
    r = ecef_from_latlon(0.0, 0.0)
    geo = ecef_to_latlon(r)
    assert abs(geo["lat"]) < 0.1
    assert abs(geo["lon"]) < 0.1
    # At North Pole
    r = ecef_from_latlon(90.0, 0.0)
    geo = ecef_to_latlon(r)
    assert abs(geo["lat"] - 90.0) < 0.1

def test_eci_to_ecef():
    from app.physics.propagation import rotate_eci_to_ecef
    r_eci = [7000.0, 0.0, 0.0]
    v_eci = [0.0, 7.5, 0.0]
    r_ecef, v_ecef = rotate_eci_to_ecef(r_eci, v_eci, 0.0)  # gmst=0
    assert abs(r_ecef[0] - 7000.0) < 0.1

def test_propagate_orbit():
    from app.physics.propagation import propagate_orbit
    result = propagate_orbit(
        a=6771.0, e=0.001, inc_deg=53.0,
        raan_deg=0.0, arg_pe_deg=0.0, M0_deg=0.0,
        j2_enabled=True, samples_per_orbit=36, total_orbits=1,
    )
    assert "data_points" in result
    assert "ground_track" in result
    assert len(result["data_points"]) == 36
    assert result["orbit_period"] > 0
    # Check data point structure
    pt = result["data_points"][0]
    for key in ["t", "r_eci", "v_eci", "r_ecef", "v_ecef", "lat", "lon", "alt"]:
        assert key in pt, f"Missing key: {key}"

def test_propagate_orbit_with_epoch():
    from app.physics.propagation import propagate_orbit
    result = propagate_orbit(
        a=6771.0, e=0.001, inc_deg=53.0,
        raan_deg=0.0, arg_pe_deg=0.0, M0_deg=0.0,
        j2_enabled=True, epoch_iso="2025-06-15T12:00:00Z",
        samples_per_orbit=36, total_orbits=1,
    )
    assert len(result["data_points"]) == 36

test("J2 secular rates", test_j2_secular_rates)
test("enhanced secular rates (J3+J4)", test_enhanced_secular_rates)
test("date_to_julian", test_date_to_julian)
test("gmst_from_date", test_gmst)
test("ecef <-> latlon roundtrip", test_ecef_latlon)
test("rotate_eci_to_ecef", test_eci_to_ecef)
test("propagate_orbit", test_propagate_orbit)
test("propagate_orbit with epoch", test_propagate_orbit_with_epoch)


# ========================================================================
# 4. PHYSICS: GEOMETRY
# ========================================================================
section("4. Physics: Link Geometry")

def test_los_elevation():
    from app.physics.geometry import los_elevation
    station = {"lat": 40.0, "lon": 2.0}
    # Satellite directly overhead at ~400km
    from app.physics.propagation import ecef_from_latlon
    from app.physics.constants import EARTH_RADIUS_KM
    r = ecef_from_latlon(40.0, 2.0, EARTH_RADIUS_KM + 400.0)
    result = los_elevation(station, r)
    assert "distanceKm" in result
    assert "elevationDeg" in result
    assert "azimuthDeg" in result
    assert result["elevationDeg"] > 80.0, f"elev={result['elevationDeg']}"
    assert result["distanceKm"] > 300, f"dist={result['distanceKm']}"

def test_geometric_loss():
    from app.physics.geometry import geometric_loss
    result = geometric_loss(500.0, 0.6, 1.0, 810.0)
    assert "coupling" in result
    assert "lossDb" in result
    assert 0 < result["coupling"] <= 1.0
    assert result["lossDb"] >= 0

def test_doppler_factor():
    from app.physics.geometry import doppler_factor
    station = {"lat": 40.0, "lon": 2.0}
    r = [7000.0, 0.0, 0.0]
    v = [0.0, 7.5, 0.0]
    result = doppler_factor(station, r, v, 810.0)
    assert "factor" in result
    assert "observedWavelength" in result
    # Doppler factor should be close to 1
    assert abs(result["factor"] - 1.0) < 0.001

def test_compute_station_metrics():
    from app.physics.geometry import compute_station_metrics
    from app.physics.propagation import propagate_orbit
    prop = propagate_orbit(6771.0, 0.001, 53.0, 0.0, 0.0, 0.0,
                           samples_per_orbit=36, total_orbits=1)
    station = {"lat": 40.0, "lon": 2.0}
    optics = {"satAperture": 0.6, "groundAperture": 1.0, "wavelength": 810}
    metrics = compute_station_metrics(prop["data_points"], station, optics)
    for key in ["distanceKm", "elevationDeg", "lossDb", "doppler", "azimuthDeg"]:
        assert key in metrics
        assert len(metrics[key]) == 36

test("los_elevation (overhead)", test_los_elevation)
test("geometric_loss", test_geometric_loss)
test("doppler_factor", test_doppler_factor)
test("compute_station_metrics", test_compute_station_metrics)


# ========================================================================
# 5. PHYSICS: QKD PROTOCOLS
# ========================================================================
section("5. Physics: QKD Protocols")

def test_bb84():
    from app.physics.qkd import calculate_bb84
    params = {
        "photonRate": 1e9,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_bb84(params)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "qber" in result
    assert "secureKeyRate" in result
    assert result["protocol"] == "BB84"
    assert result["qber"] >= 0
    assert result["secureKeyRate"] >= 0

def test_bb84_high_loss():
    from app.physics.qkd import calculate_bb84
    params = {
        "photonRate": 1e9,
        "channelLossdB": 80.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_bb84(params)
    # High loss should make QBER > threshold, so SKR = 0
    assert result["secureKeyRate"] == 0

def test_e91():
    from app.physics.qkd import calculate_e91
    params = {
        "photonRate": 1e9,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_e91(params)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["protocol"] == "E91"
    assert result["qber"] >= 0

def test_cvqkd():
    from app.physics.qkd import calculate_cvqkd
    params = {
        "channelLossdB": 10.0,
        "detectorEfficiency": 0.5,
    }
    result = calculate_cvqkd(params)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["protocol"] == "CV-QKD"
    assert result["secureKeyRate"] >= 0

def test_qkd_dispatcher():
    from app.physics.qkd import calculate_qkd
    params = {
        "photonRate": 1e9,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    for proto in ["bb84", "e91", "cv-qkd", "cvqkd"]:
        result = calculate_qkd(proto, params)
        assert "error" not in result, f"Protocol {proto} error: {result.get('error')}"

def test_qkd_unknown_protocol():
    from app.physics.qkd import calculate_qkd
    result = calculate_qkd("unknown", {})
    assert "error" in result

def test_bb84_invalid_input():
    from app.physics.qkd import calculate_bb84
    result = calculate_bb84({})
    assert "error" in result

test("BB84 basic", test_bb84)
test("BB84 high loss", test_bb84_high_loss)
test("E91 basic", test_e91)
test("CV-QKD basic", test_cvqkd)
test("QKD dispatcher", test_qkd_dispatcher)
test("QKD unknown protocol", test_qkd_unknown_protocol)
test("BB84 invalid input", test_bb84_invalid_input)


# ========================================================================
# 6. PHYSICS: IRRADIANCE
# ========================================================================
section("6. Physics: Solar Irradiance")

def test_irradiance_day():
    from app.physics.irradiance import compute_irradiance
    dt = datetime(2025, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    result = compute_irradiance(40.0, 2.0, dt, altitude_m=0.0)
    assert result["is_day"] == True
    assert result["ghi_w_m2"] > 0
    assert result["dni_w_m2"] > 0
    assert result["solar_elevation_deg"] > 0
    assert result["air_mass"] is not None and result["air_mass"] > 0

def test_irradiance_night():
    from app.physics.irradiance import compute_irradiance
    dt = datetime(2025, 6, 21, 1, 0, 0, tzinfo=timezone.utc)
    result = compute_irradiance(40.0, 2.0, dt, altitude_m=0.0)
    assert result["is_day"] == False
    assert result["ghi_w_m2"] == 0.0
    assert result["dni_w_m2"] == 0.0

def test_irradiance_polar():
    from app.physics.irradiance import compute_irradiance
    # Summer at North Pole - midnight sun
    dt = datetime(2025, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    result = compute_irradiance(89.0, 0.0, dt)
    assert result["day_length_h"] == 24.0

def test_irradiance_altitude_effect():
    from app.physics.irradiance import compute_irradiance
    dt = datetime(2025, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    r0 = compute_irradiance(40.0, 2.0, dt, 0.0)
    r_high = compute_irradiance(40.0, 2.0, dt, 5000.0)
    # Higher altitude = less air mass = more irradiance
    assert r_high["ghi_w_m2"] >= r0["ghi_w_m2"], \
        f"High={r_high['ghi_w_m2']}, Low={r0['ghi_w_m2']}"

def test_irradiance_timeline():
    from app.physics.irradiance import compute_irradiance_timeline
    dt = datetime(2025, 6, 21, 0, 0, 0, tzinfo=timezone.utc)
    offsets = [h * 3600.0 for h in range(24)]
    result = compute_irradiance_timeline(40.0, 2.0, dt, offsets)
    assert len(result["ghi_w_m2"]) == 24
    assert len(result["is_day"]) == 24
    # Should have some daytime and some nighttime
    assert True in result["is_day"]
    assert False in result["is_day"]

test("irradiance daytime", test_irradiance_day)
test("irradiance nighttime", test_irradiance_night)
test("irradiance polar (midnight sun)", test_irradiance_polar)
test("irradiance altitude effect", test_irradiance_altitude_effect)
test("irradiance_timeline", test_irradiance_timeline)


# ========================================================================
# 7. PHYSICS: SOLAR EPHEMERIS
# ========================================================================
section("7. Physics: Solar Ephemeris")

def test_solar_ephemeris():
    from app.physics.solar import compute_solar_ephemeris
    result = compute_solar_ephemeris(
        "2025-06-21T12:00:00Z",
        [0.0, 3600.0, 7200.0],
    )
    assert len(result["sun_dir_eci"]) == 3
    assert len(result["gmst_rad"]) == 3
    assert len(result["subsolar_lat_lon"]) == 3
    # Sun direction should be unit vector
    d = result["sun_dir_eci"][0]
    norm = math.sqrt(sum(c*c for c in d))
    assert abs(norm - 1.0) < 0.01

def test_sun_direction():
    from app.physics.solar import sun_direction_eci, _to_astro_time
    dt = datetime(2025, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    t = _to_astro_time(dt)
    x, y, z = sun_direction_eci(t)
    norm = math.sqrt(x*x + y*y + z*z)
    assert abs(norm - 1.0) < 0.001

def test_subsolar_point():
    from app.physics.solar import subsolar_point_from_dir
    # At summer solstice, subsolar lat should be ~23.4 deg
    lat, lon = subsolar_point_from_dir(1.0, 0.0, 0.4, 0.0)
    assert abs(lat - math.degrees(math.asin(0.4))) < 1.0

def test_scene_timeline():
    from app.physics.solar import compute_scene_timeline
    result = compute_scene_timeline(
        "2025-06-21T12:00:00Z", 86400.0, 3600.0,
    )
    assert len(result["t_offsets_s"]) == 25
    assert len(result["earth_pos_eci_au"]) == 25
    assert len(result["sun_dir_eci"]) == 25

test("solar ephemeris", test_solar_ephemeris)
test("sun_direction_eci", test_sun_direction)
test("subsolar_point_from_dir", test_subsolar_point)
test("compute_scene_timeline", test_scene_timeline)


# ========================================================================
# 8. PHYSICS: WALKER CONSTELLATION
# ========================================================================
section("8. Physics: Walker Constellation")

def test_generate_walker():
    from app.physics.walker import generate_walker
    sats = generate_walker(24, 6, 1, 500.0, 53.0)
    assert len(sats) == 24
    # Check structure
    for s in sats:
        assert "semiMajor" in s
        assert "eccentricity" in s
        assert "inclination" in s
        assert "raan" in s
        assert "meanAnomaly" in s

def test_sun_sync_inclination():
    from app.physics.walker import sun_synchronous_inclination
    inc = sun_synchronous_inclination(600.0)
    assert 90.0 < inc < 110.0, f"inc={inc}"

def test_sun_sync_inclination_invalid():
    from app.physics.walker import sun_synchronous_inclination
    # Very high altitude where cos_i > 1 (no SSO possible)
    try:
        sun_synchronous_inclination(40000.0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

def test_validate_sun_sync():
    from app.physics.walker import validate_sun_synchronous
    result = validate_sun_synchronous(600.0, 97.8)
    assert "isSunSynchronous" in result
    assert "raanDriftDegPerDay" in result

def test_repeat_ground_track():
    from app.physics.walker import repeat_ground_track_sma
    a, alt = repeat_ground_track_sma(15)
    assert a > 6378.137
    assert alt > 0

def test_ltan_to_raan():
    from app.physics.walker import ltan_to_raan
    raan = ltan_to_raan(10.5, "2025-03-20T12:00:00Z")
    assert 0 <= raan < 360

def test_compute_sso_orbit():
    from app.physics.walker import compute_sso_orbit
    result = compute_sso_orbit(600.0, 0.0, 10.5, "2025-06-21T00:00:00Z")
    assert result["is_sun_synchronous"] == True
    assert result["inclination_deg"] > 90

def test_validate_elements():
    from app.physics.walker import validate_elements
    valid, err = validate_elements(7000.0, 0.001, math.radians(53.0))
    assert valid == True
    assert err is None
    # Invalid: below surface
    valid, err = validate_elements(5000.0, 0.0, 0.5)
    assert valid == False

test("generate_walker", test_generate_walker)
test("sun_synchronous_inclination", test_sun_sync_inclination)
test("sun_sync inclination invalid alt", test_sun_sync_inclination_invalid)
test("validate_sun_synchronous", test_validate_sun_sync)
test("repeat_ground_track_sma", test_repeat_ground_track)
test("ltan_to_raan", test_ltan_to_raan)
test("compute_sso_orbit", test_compute_sso_orbit)
test("validate_elements", test_validate_elements)


# ========================================================================
# 9. SERVICES: IRRADIANCE SERVICE
# ========================================================================
section("9. Services: Irradiance")

def test_irradiance_service_analytical():
    from app.services.irradiance_svc import IrradianceService, IrradianceQuery
    svc = IrradianceService()
    dt = datetime(2025, 6, 21, 12, 0, 0)
    q = IrradianceQuery(lat=40.0, lon=2.0, timestamp=dt, method="analytical")
    result = svc.get_irradiance(q)
    assert result["method"] == "analytical"
    assert result["ghi_w_m2"] > 0

def test_irradiance_service_unknown_method():
    from app.services.irradiance_svc import IrradianceService, IrradianceQuery, IrradianceParameterError
    svc = IrradianceService()
    dt = datetime(2025, 6, 21, 12, 0, 0)
    q = IrradianceQuery(lat=40.0, lon=2.0, timestamp=dt, method="bogus")
    try:
        svc.get_irradiance(q)
        assert False, "Should have raised"
    except IrradianceParameterError:
        pass

test("irradiance service analytical", test_irradiance_service_analytical)
test("irradiance service unknown method", test_irradiance_service_unknown_method)


# ========================================================================
# 10. SERVICES: OGS STORE
# ========================================================================
section("10. Services: OGS Store")

def test_ogs_store():
    import tempfile, json
    from pathlib import Path
    from app.services.ogs_store import OGSStore
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump([], f)
        path = Path(f.name)
    store = OGSStore(path)
    # List should be empty
    assert store.list() == []
    # Upsert
    rec = store.upsert({"name": "Test OGS", "lat": 40.0, "lon": 2.0})
    assert "id" in rec
    assert len(store.list()) == 1
    # Upsert same id
    rec2 = store.upsert({"id": rec["id"], "name": "Updated", "lat": 41.0, "lon": 3.0})
    assert len(store.list()) == 1
    assert rec2["name"] == "Updated"
    # Delete
    assert store.delete(rec["id"]) == True
    assert len(store.list()) == 0
    # Delete non-existent
    assert store.delete("nonexistent") == False
    # Overwrite
    store.overwrite([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}])
    assert len(store.list()) == 2
    # Delete all
    store.delete_all()
    assert store.list() == []
    path.unlink()

test("OGS store CRUD", test_ogs_store)


# ========================================================================
# 11. SERVICES: DATABASE
# ========================================================================
section("11. Services: Database")

def test_database():
    import tempfile, os
    from pathlib import Path
    from app.services.database import DatabaseGateway, UserAlreadyExistsError
    
    tmpdir = tempfile.mkdtemp()
    try:
        base = Path(tmpdir)
        (base / "data").mkdir()
        gw = DatabaseGateway(base)
        gw.initialise()
        
        # Create user
        user = gw.create_user("testuser", "testpass123")
        assert user.username == "testuser"
        assert user.id > 0
        
        # Duplicate user
        try:
            gw.create_user("testuser", "otherpass")
            assert False, "Should have raised"
        except UserAlreadyExistsError:
            pass
        
        # Get by id
        u = gw.get_user_by_id(user.id)
        assert u is not None
        assert u.username == "testuser"
        
        # Get by username
        u = gw.get_user_by_username("testuser")
        assert u is not None
        
        # Verify credentials
        u = gw.verify_credentials("testuser", "testpass123")
        assert u is not None
        # Wrong password
        u = gw.verify_credentials("testuser", "wrong")
        assert u is None
        
        # Count users
        assert gw.count_users() == 1
        
        # Chat messages
        chat = gw.store_chat_message(user.id, "Hello world")
        assert chat.message == "Hello world"
        assert chat.username == "testuser"
        
        msgs = gw.list_chat_messages()
        assert len(msgs) == 1
    finally:
        # On Windows, SQLite WAL files may linger; ignore cleanup errors
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

test("database CRUD", test_database)


# ========================================================================
# 12. SERVICES: TLE SERVICE
# ========================================================================
section("12. Services: TLE Service")

def test_tle_service_list():
    from app.services.tle_service import TleService
    svc = TleService()
    groups = svc.list_groups()
    assert "starlink" in groups
    assert "gps" in groups

def test_tle_service_unknown():
    from app.services.tle_service import TleService, TleGroupNotFoundError
    svc = TleService()
    try:
        svc.get_group("nonexistent")
        assert False, "Should have raised"
    except TleGroupNotFoundError:
        pass

test("TLE service list groups", test_tle_service_list)
test("TLE service unknown group", test_tle_service_unknown)


# ========================================================================
# 13. MODELS
# ========================================================================
section("13. Models (Pydantic)")

def test_pydantic_models():
    from app.models import (
        OGSLocation, UserCreate, AtmosRequest, IrradianceRequest,
        WeatherFieldRequest, SolveRequest, is_in_europe_bbox, normalize_username,
    )
    # OGSLocation
    ogs = OGSLocation(name="Test", lat=40.0, lon=2.0)
    assert ogs.aperture_m == 1.0  # default
    
    # is_in_europe_bbox
    assert is_in_europe_bbox(40.0, 2.0) == True
    assert is_in_europe_bbox(0.0, 0.0) == False
    
    # normalize_username
    assert normalize_username("  TestUser  ") == "testuser"
    
    # SolveRequest defaults
    sr = SolveRequest()
    assert sr.semi_major_axis == 6771.0
    assert sr.wavelength_nm == 810.0

def test_atmos_request():
    from app.models import AtmosRequest
    req = AtmosRequest(
        lat=40.0, lon=2.0, time="2025-06-21T12:00:00Z",
        ground_cn2_day=5e-14, ground_cn2_night=5e-15,
    )
    assert req.model == "hufnagel-valley"
    assert req.wavelength_nm == 810.0

def test_irradiance_request():
    from app.models import IrradianceRequest
    req = IrradianceRequest(lat=40.0, lon=2.0, time="2025-06-21T12:00:00Z")
    assert req.method == "analytical"
    assert req.altitude_m == 0.0

test("pydantic models", test_pydantic_models)
test("AtmosRequest defaults", test_atmos_request)
test("IrradianceRequest defaults", test_irradiance_request)


# ========================================================================
# 14. API ENDPOINT TESTING (using TestClient)
# ========================================================================
section("14. API Endpoints (FastAPI TestClient)")

def test_app_creation():
    from app.backend import create_app
    application = create_app()
    assert application is not None
    assert application.title == "QKD Europe Planner"

test("app creation", test_app_creation)

# Use TestClient for endpoint tests
try:
    from fastapi.testclient import TestClient
    from app.backend import app as test_app
    client = TestClient(test_app)
    HAS_CLIENT = True
except Exception as e:
    print(f"  [WARN] Could not create TestClient: {e}")
    HAS_CLIENT = False

if HAS_CLIENT:
    def test_health():
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_page():
        r = client.get("/")
        assert r.status_code == 200

    def test_ogs_list():
        r = client.get("/api/ogs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_ogs_add_europe():
        r = client.post("/api/ogs", json={
            "name": "Test Station",
            "lat": 40.0,
            "lon": 2.0,
            "aperture_m": 1.0,
        })
        assert r.status_code == 200

    def test_ogs_add_outside_europe():
        r = client.post("/api/ogs", json={
            "name": "Equatorial Station",
            "lat": 0.0,
            "lon": 0.0,
            "aperture_m": 1.0,
        })
        assert r.status_code == 200

    def test_orbital_info():
        r = client.get("/api/orbital/info")
        assert r.status_code == 200
        data = r.json()
        assert data["j2_available"] == True

    def test_orbital_sun_sync():
        r = client.get("/api/orbital/sun-synchronous?altitude_km=600")
        assert r.status_code == 200
        data = r.json()
        assert data["is_sun_synchronous"] == True
        assert data["inclination_deg"] > 90

    def test_orbital_sso_design():
        r = client.get("/api/orbital/sun-synchronous-orbit?altitude_km=600&ltan_hours=10.5")
        assert r.status_code == 200
        data = r.json()
        assert "inclination_deg" in data
        assert "raan_deg" in data

    def test_orbital_walker():
        r = client.get("/api/orbital/walker-constellation?T=24&P=6&F=1&altitude_km=500&inclination_deg=53")
        assert r.status_code == 200
        data = r.json()
        assert data["total_satellites"] == 24

    def test_orbital_rgt():
        r = client.get("/api/orbital/repeat-ground-track?revolutions_per_day=15")
        assert r.status_code == 200
        data = r.json()
        assert data["altitude_km"] > 0

    def test_solve_basic():
        r = client.post("/api/solve", json={
            "semi_major_axis": 6771.0,
            "eccentricity": 0.001,
            "inclination_deg": 53.0,
            "samples_per_orbit": 36,
            "total_orbits": 1,
        })
        assert r.status_code == 200
        data = r.json()
        assert "orbit" in data
        assert "ground_track" in data
        assert data["orbit"]["samples"] == 36

    def test_solve_with_station():
        r = client.post("/api/solve", json={
            "semi_major_axis": 6771.0,
            "eccentricity": 0.001,
            "inclination_deg": 53.0,
            "station_lat": 40.0,
            "station_lon": 2.0,
            "samples_per_orbit": 36,
            "total_orbits": 1,
        })
        assert r.status_code == 200
        data = r.json()
        assert "station_metrics" in data

    def test_solve_with_qkd():
        r = client.post("/api/solve", json={
            "semi_major_axis": 6771.0,
            "eccentricity": 0.001,
            "inclination_deg": 53.0,
            "station_lat": 40.0,
            "station_lon": 2.0,
            "qkd_protocol": "bb84",
            "samples_per_orbit": 36,
            "total_orbits": 1,
        })
        assert r.status_code == 200
        data = r.json()
        # qkd key may be present (only if satellite is visible)
        assert "orbit" in data

    def test_solar_endpoint():
        r = client.post("/api/solar", json={
            "epoch_iso": "2025-06-21T12:00:00Z",
            "t_offsets_s": [0.0, 3600.0, 7200.0],
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["sun_dir_eci"]) == 3

    def test_scene_timeline_endpoint():
        r = client.post("/api/scene-timeline", json={
            "epoch_iso": "2025-06-21T12:00:00Z",
            "interval_s": 86400.0,
            "step_s": 3600.0,
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["t_offsets_s"]) == 25

    def test_irradiance_endpoint():
        r = client.post("/api/irradiance", json={
            "lat": 40.0,
            "lon": 2.0,
            "time": "2025-06-21T12:00:00Z",
            "method": "analytical",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ghi_w_m2"] > 0

    def test_tles_list():
        r = client.get("/api/tles")
        assert r.status_code == 200
        data = r.json()
        assert "groups" in data

    def test_users_count():
        r = client.get("/api/users/count")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data

    def test_chats_list():
        r = client.get("/api/chats")
        assert r.status_code == 200

    test("GET /health", test_health)
    test("GET / (root page)", test_root_page)
    test("GET /api/ogs", test_ogs_list)
    test("POST /api/ogs (Europe)", test_ogs_add_europe)
    test("POST /api/ogs (outside Europe)", test_ogs_add_outside_europe)
    test("GET /api/orbital/info", test_orbital_info)
    test("GET /api/orbital/sun-synchronous", test_orbital_sun_sync)
    test("GET /api/orbital/sun-synchronous-orbit", test_orbital_sso_design)
    test("GET /api/orbital/walker-constellation", test_orbital_walker)
    test("GET /api/orbital/repeat-ground-track", test_orbital_rgt)
    test("POST /api/solve (basic)", test_solve_basic)
    test("POST /api/solve (with station)", test_solve_with_station)
    test("POST /api/solve (with QKD)", test_solve_with_qkd)
    test("POST /api/solar", test_solar_endpoint)
    test("POST /api/scene-timeline", test_scene_timeline_endpoint)
    test("POST /api/irradiance", test_irradiance_endpoint)
    test("GET /api/tles", test_tles_list)
    test("GET /api/users/count", test_users_count)
    test("GET /api/chats", test_chats_list)


# ========================================================================
# 15. QKD SOLVER INTEGRATION: channelLossdB bug check
# ========================================================================
section("15. Solver QKD Integration: channelLossdB check")

def test_solver_qkd_channel_loss():
    """The solver passes 'coupling' but QKD expects 'channelLossdB'.
    Verify the solver constructs qkd_params correctly."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest
    req = SolveRequest(
        semi_major_axis=6771.0,
        eccentricity=0.001,
        inclination_deg=53.0,
        station_lat=40.0,
        station_lon=2.0,
        qkd_protocol="bb84",
        samples_per_orbit=36,
        total_orbits=1,
    )
    result = _run_solve(req)
    # Check that QKD results exist (satellite may or may not be visible)
    if "qkd" in result and len(result["qkd"]) > 0:
        for qkd_entry in result["qkd"]:
            # Should NOT have an error about missing channelLossdB
            if "error" in qkd_entry:
                assert "channelLossdB" not in qkd_entry["error"], \
                    f"QKD error: {qkd_entry['error']}"

test("solver QKD channelLossdB integration", test_solver_qkd_channel_loss)


# ========================================================================
# 16. PHYSICS: LINK BUDGET
# ========================================================================
section("16. Physics: Link Budget")

def test_lb_atm_loss_monotonic():
    """Atmospheric loss must increase as elevation decreases."""
    from app.physics.link_budget import atm_loss_db
    prev = 0.0
    for el in [90, 60, 30, 10, 5]:
        loss = atm_loss_db(el, 1.0, 0.5)
        assert loss >= prev, f"Not monotonic at {el}°: {loss} < {prev}"
        prev = loss

def test_lb_atm_loss_zero_elev():
    """Atm loss at elev<=0 must be 0."""
    from app.physics.link_budget import atm_loss_db
    assert atm_loss_db(0, 1.0, 0.5) == 0.0
    assert atm_loss_db(-10, 2.0, 1.0) == 0.0

def test_lb_atm_loss_zenith():
    """At 90° elev (zenith), loss = zenith_aod + zenith_abs."""
    from app.physics.link_budget import atm_loss_db
    loss = atm_loss_db(90.0, 1.0, 0.5)
    assert abs(loss - 1.5) < 0.01

def test_lb_atm_loss_no_input():
    """With zero zenith values, atm loss is always 0."""
    from app.physics.link_budget import atm_loss_db
    for el in [90, 30, 5]:
        assert atm_loss_db(el, 0.0, 0.0) == 0.0

def test_lb_pointing_zero():
    """Zero pointing error => 0 dB loss."""
    from app.physics.link_budget import pointing_loss_db
    assert pointing_loss_db(0.0, 1e-5) == 0.0

def test_lb_pointing_increases():
    """Pointing loss increases with pointing error."""
    from app.physics.link_budget import pointing_loss_db
    div = 1.22 * 810e-9 / 0.15
    prev = 0.0
    for pe in [0, 1, 2, 5, 10]:
        loss = pointing_loss_db(pe, div)
        assert loss >= prev, f"Not monotonic at {pe} urad"
        prev = loss

def test_lb_pointing_saturation():
    """Very large pointing error should be capped, not overflow."""
    from app.physics.link_budget import pointing_loss_db
    div = 1.22 * 810e-9 / 0.15
    loss = pointing_loss_db(1000, div)
    assert loss == 150.0  # capped

def test_lb_scint_no_layers():
    """With no Cn2 layers, scintillation loss is 0."""
    from app.physics.link_budget import scintillation_loss_db
    assert scintillation_loss_db(45, 810, 1.0, None) == 0.0
    assert scintillation_loss_db(45, 810, 1.0, []) == 0.0
    assert scintillation_loss_db(45, 810, 1.0, [(100, 1e-14)]) == 0.0  # only 1 layer

def test_lb_scint_increases_low_elev():
    """Scintillation loss should generally increase at lower elevation."""
    from app.physics.link_budget import scintillation_loss_db
    def hv57(h):
        return (0.00594 * 441 * (1e-5*h)**10 * math.exp(-h/1000)
                + 2.7e-16 * math.exp(-h/1500)
                + 1.7e-14 * math.exp(-h/100))
    layers = [(h, hv57(h)) for h in range(100, 20001, 200)]
    loss_90 = scintillation_loss_db(90, 810, 1.0, layers, 0.01)
    loss_20 = scintillation_loss_db(20, 810, 1.0, layers, 0.01)
    assert loss_20 > loss_90, f"Expected loss at 20° ({loss_20}) > 90° ({loss_90})"

def test_lb_scint_non_negative():
    """Scintillation loss must be >= 0."""
    from app.physics.link_budget import scintillation_loss_db
    def hv57(h):
        return (0.00594 * 441 * (1e-5*h)**10 * math.exp(-h/1000)
                + 2.7e-16 * math.exp(-h/1500)
                + 1.7e-14 * math.exp(-h/100))
    layers = [(h, hv57(h)) for h in range(100, 20001, 200)]
    for el in [90, 45, 20, 10, 5]:
        loss = scintillation_loss_db(el, 810, 1.0, layers, 0.01)
        assert loss >= 0, f"Negative scint loss at {el}°: {loss}"

def test_lb_scint_zero_elev():
    """Scintillation at elev <= 0 should be 0."""
    from app.physics.link_budget import scintillation_loss_db
    layers = [(h, 1e-15) for h in range(100, 5001, 500)]
    assert scintillation_loss_db(0, 810, 1.0, layers) == 0.0
    assert scintillation_loss_db(-5, 810, 1.0, layers) == 0.0

def test_lb_background_scaling_fov():
    """Background CPS scales with FOV² (solid angle)."""
    from app.physics.link_budget import background_noise_cps
    base = background_noise_cps(1e-3, 1.0, 1.0, 1.0, 810)
    doubled = background_noise_cps(1e-3, 2.0, 1.0, 1.0, 810)
    assert base > 0
    assert abs(doubled / base - 4.0) < 0.01, f"Ratio = {doubled/base}"

def test_lb_background_scaling_dlambda():
    """Background CPS scales linearly with Δλ."""
    from app.physics.link_budget import background_noise_cps
    base = background_noise_cps(1e-3, 1.0, 1.0, 1.0, 810)
    doubled = background_noise_cps(1e-3, 1.0, 1.0, 2.0, 810)
    assert abs(doubled / base - 2.0) < 0.01, f"Ratio = {doubled/base}"

def test_lb_background_scaling_aperture():
    """Background CPS scales with aperture² (area)."""
    from app.physics.link_budget import background_noise_cps
    base = background_noise_cps(1e-3, 1.0, 1.0, 1.0, 810)
    doubled = background_noise_cps(1e-3, 1.0, 2.0, 1.0, 810)
    assert abs(doubled / base - 4.0) < 0.01, f"Ratio = {doubled/base}"

def test_lb_background_zero_inputs():
    """Background CPS is 0 when any input is 0."""
    from app.physics.link_budget import background_noise_cps
    assert background_noise_cps(0, 1.0, 1.0, 1.0, 810) == 0.0
    assert background_noise_cps(1e-3, 0, 1.0, 1.0, 810) == 0.0
    assert background_noise_cps(1e-3, 1.0, 0, 1.0, 810) == 0.0
    assert background_noise_cps(1e-3, 1.0, 1.0, 0, 810) == 0.0

def test_lb_total_loss():
    """Total loss is sum of components, clamped >= 0."""
    from app.physics.link_budget import total_link_loss_db
    assert total_link_loss_db(10, 2, 1, 0.5, 1.5) == 15.0
    assert total_link_loss_db(0, 0, 0, 0, 0) == 0.0

def test_lb_coupling_bounds():
    """Coupling is in (0, 1]."""
    from app.physics.link_budget import coupling_from_loss
    assert coupling_from_loss(0.0) == 1.0
    c = coupling_from_loss(30.0)
    assert 0 < c < 1
    assert abs(c - 1e-3) < 1e-6

def test_lb_erfinv_accuracy():
    """erfinv roundtrip accuracy."""
    from app.physics.link_budget import _erfinv_approx
    for x in [-0.99, -0.5, 0.0, 0.5, 0.98]:
        ei = _erfinv_approx(x)
        roundtrip = math.erf(ei)
        assert abs(roundtrip - x) < 1e-6, f"erfinv({x}): erf(.)={roundtrip}"

test("atm_loss monotonic vs elevation", test_lb_atm_loss_monotonic)
test("atm_loss zero at elev<=0", test_lb_atm_loss_zero_elev)
test("atm_loss at zenith", test_lb_atm_loss_zenith)
test("atm_loss zero when no zenith input", test_lb_atm_loss_no_input)
test("pointing_loss zero error", test_lb_pointing_zero)
test("pointing_loss increases with error", test_lb_pointing_increases)
test("pointing_loss saturation cap", test_lb_pointing_saturation)
test("scintillation no layers => 0", test_lb_scint_no_layers)
test("scintillation increases at low elev", test_lb_scint_increases_low_elev)
test("scintillation non-negative", test_lb_scint_non_negative)
test("scintillation zero at elev<=0", test_lb_scint_zero_elev)
test("background scales with FOV²", test_lb_background_scaling_fov)
test("background scales with Δλ", test_lb_background_scaling_dlambda)
test("background scales with aperture²", test_lb_background_scaling_aperture)
test("background zero inputs", test_lb_background_zero_inputs)
test("total_link_loss sum", test_lb_total_loss)
test("coupling bounds", test_lb_coupling_bounds)
test("erfinv accuracy", test_lb_erfinv_accuracy)


# ========================================================================
# 17. GEOMETRY: LINK BUDGET INTEGRATION
# ========================================================================
section("17. Geometry: Link Budget Integration")

def test_metrics_backward_compat():
    """Without link_budget_cfg, lossDb == geoLossDb (backward compat)."""
    from app.physics.geometry import compute_station_metrics
    from app.physics.propagation import propagate_orbit
    prop = propagate_orbit(6771.0, 0.001, 53.0, 0.0, 0.0, 0.0,
                           samples_per_orbit=36, total_orbits=1)
    station = {"lat": 40.0, "lon": 2.0}
    optics = {"satAperture": 0.6, "groundAperture": 1.0, "wavelength": 810}
    m = compute_station_metrics(prop["data_points"], station, optics)
    for key in ["geoLossDb", "atmLossDb", "pointingLossDb",
                "scintLossDb", "fixedLossDb", "totalLossDb",
                "couplingTotal", "backgroundCps"]:
        assert key in m, f"Missing key: {key}"
        assert len(m[key]) == 36
    # lossDb == geoLossDb when no extras
    for i in range(36):
        assert abs(m["lossDb"][i] - m["geoLossDb"][i]) < 1e-6, \
            f"Sample {i}: lossDb != geoLossDb"
        assert m["atmLossDb"][i] == 0.0
        assert m["pointingLossDb"][i] == 0.0
        assert m["scintLossDb"][i] == 0.0
        assert m["fixedLossDb"][i] == 0.0
        assert m["backgroundCps"][i] == 0.0

def test_metrics_with_link_budget():
    """With link_budget_cfg, total loss includes all components."""
    from app.physics.geometry import compute_station_metrics
    from app.physics.propagation import propagate_orbit
    prop = propagate_orbit(6771.0, 0.001, 53.0, 0.0, 0.0, 0.0,
                           samples_per_orbit=36, total_orbits=1)
    station = {"lat": 40.0, "lon": 2.0}
    optics = {"satAperture": 0.15, "groundAperture": 1.0, "wavelength": 810}
    lb_cfg = {
        "pointing_error_urad": 2.0,
        "atm_zenith_aod_db": 1.0,
        "atm_zenith_abs_db": 0.3,
        "fixed_optics_loss_db": 1.5,
        "scintillation_enabled": False,
        "background_enabled": True,
        "background_Hrad_W_m2_sr_um": 1e-3,
        "background_fov_mrad": 1.0,
        "background_delta_lambda_nm": 1.0,
    }
    m = compute_station_metrics(prop["data_points"], station, optics,
                                link_budget_cfg=lb_cfg)
    for i in range(36):
        elev = m["elevationDeg"][i]
        total = m["totalLossDb"][i]
        geo = m["geoLossDb"][i]
        if elev > 0:
            # total >= geo when extras are active
            assert total >= geo, f"Sample {i}: total {total} < geo {geo}"
            # components should sum to total
            comp_sum = (m["geoLossDb"][i] + m["atmLossDb"][i] +
                        m["pointingLossDb"][i] + m["scintLossDb"][i] +
                        m["fixedLossDb"][i])
            assert abs(total - comp_sum) < 1e-6, \
                f"Sample {i}: total {total} != sum {comp_sum}"
            # coupling in (0, 1]
            assert 0 < m["couplingTotal"][i] <= 1.0
            # background > 0 when enabled and elev > 0
            assert m["backgroundCps"][i] > 0

def test_metrics_coupling_consistency():
    """couplingTotal should match 10^(-totalLossDb/10)."""
    from app.physics.geometry import compute_station_metrics
    from app.physics.propagation import propagate_orbit
    prop = propagate_orbit(6771.0, 0.001, 53.0, 0.0, 0.0, 0.0,
                           samples_per_orbit=36, total_orbits=1)
    station = {"lat": 40.0, "lon": 2.0}
    optics = {"satAperture": 0.15, "groundAperture": 1.0, "wavelength": 810}
    lb_cfg = {"pointing_error_urad": 1.0, "atm_zenith_aod_db": 0.5,
              "fixed_optics_loss_db": 1.0}
    m = compute_station_metrics(prop["data_points"], station, optics,
                                link_budget_cfg=lb_cfg)
    for i in range(36):
        expected = min(1.0, 10 ** (-m["totalLossDb"][i] / 10.0))
        assert abs(m["couplingTotal"][i] - expected) < 1e-9

test("metrics backward compat (no link-budget cfg)", test_metrics_backward_compat)
test("metrics with link-budget components", test_metrics_with_link_budget)
test("coupling consistency with totalLossDb", test_metrics_coupling_consistency)


# ========================================================================
# 18. SOLVER: LINK BUDGET END-TO-END
# ========================================================================
section("18. Solver: Link Budget End-to-End")

def test_solver_default_no_extras():
    """Solver with default (no link-budget) should work unchanged."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest
    req = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        samples_per_orbit=36, total_orbits=1,
    )
    result = _run_solve(req)
    m = result["station_metrics"]
    assert "geoLossDb" in m
    assert "totalLossDb" in m
    for i in range(36):
        assert abs(m["lossDb"][i] - m["geoLossDb"][i]) < 1e-6

def test_solver_link_budget_extras():
    """Solver with link-budget fields produces higher total loss."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest
    req_base = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        samples_per_orbit=36, total_orbits=1,
    )
    req_ext = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        samples_per_orbit=36, total_orbits=1,
        pointing_error_urad=3.0,
        atm_zenith_aod_db=1.0,
        atm_zenith_abs_db=0.3,
        fixed_optics_loss_db=2.0,
    )
    r1 = _run_solve(req_base)
    r2 = _run_solve(req_ext)
    m1, m2 = r1["station_metrics"], r2["station_metrics"]
    # At every visible sample, total loss should be higher with extras
    for i in range(36):
        if m1["elevationDeg"][i] > 0:
            assert m2["lossDb"][i] >= m1["lossDb"][i], \
                f"Sample {i}: ext {m2['lossDb'][i]} < base {m1['lossDb'][i]}"

def test_solver_background_dark_count():
    """When background is enabled, QKD dark_count_rate is augmented."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest
    req_no_bg = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        qkd_protocol="bb84",
        samples_per_orbit=36, total_orbits=1,
    )
    req_bg = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        qkd_protocol="bb84",
        samples_per_orbit=36, total_orbits=1,
        background_enabled=True,
        background_Hrad_W_m2_sr_um=1e-2,
        background_fov_mrad=1.0,
        background_delta_lambda_nm=10.0,
    )
    r1 = _run_solve(req_no_bg)
    r2 = _run_solve(req_bg)
    # Both should produce QKD results (if satellite visible)
    if "qkd" in r1 and len(r1["qkd"]) > 0 and "qkd" in r2 and len(r2["qkd"]) > 0:
        # With background noise, QBER should be >= without it
        q1 = r1["qkd"][0]
        q2 = r2["qkd"][0]
        if "error" not in q1 and "error" not in q2:
            assert q2["qber"] >= q1["qber"], \
                f"QBER with bg ({q2['qber']}) < without ({q1['qber']})"

def test_solver_new_fields_optional():
    """Solver accepts old payloads without new fields (backward compat)."""
    if HAS_CLIENT:
        r = client.post("/api/solve", json={
            "semi_major_axis": 6771.0,
            "eccentricity": 0.001,
            "inclination_deg": 53.0,
            "station_lat": 40.0,
            "station_lon": 2.0,
            "samples_per_orbit": 36,
            "total_orbits": 1,
        })
        assert r.status_code == 200
        data = r.json()
        assert "station_metrics" in data
        assert "geoLossDb" in data["station_metrics"]

def test_solver_api_with_link_budget():
    """Solver API accepts new link-budget fields."""
    if HAS_CLIENT:
        r = client.post("/api/solve", json={
            "semi_major_axis": 6771.0,
            "eccentricity": 0.001,
            "inclination_deg": 53.0,
            "station_lat": 40.0,
            "station_lon": 2.0,
            "pointing_error_urad": 5.0,
            "atm_zenith_aod_db": 1.0,
            "atm_zenith_abs_db": 0.2,
            "fixed_optics_loss_db": 1.5,
            "background_enabled": True,
            "background_Hrad_W_m2_sr_um": 1e-3,
            "background_fov_mrad": 0.5,
            "background_delta_lambda_nm": 1.0,
            "qkd_protocol": "bb84",
            "samples_per_orbit": 36,
            "total_orbits": 1,
        })
        assert r.status_code == 200
        data = r.json()
        m = data["station_metrics"]
        assert "geoLossDb" in m
        assert "atmLossDb" in m
        assert "pointingLossDb" in m
        assert "scintLossDb" in m
        assert "fixedLossDb" in m
        assert "couplingTotal" in m
        assert "backgroundCps" in m

def test_solver_model_new_defaults():
    """SolveRequest new fields have correct defaults."""
    from app.models import SolveRequest
    sr = SolveRequest()
    assert sr.pointing_error_urad == 0.0
    assert sr.scintillation_enabled == False
    assert sr.scintillation_p0 == 0.01
    assert sr.atm_zenith_aod_db == 0.0
    assert sr.atm_zenith_abs_db == 0.0
    assert sr.fixed_optics_loss_db == 0.0
    assert sr.background_enabled == False
    assert sr.background_Hrad_W_m2_sr_um == 0.0
    assert sr.background_fov_mrad == 0.0
    assert sr.background_delta_lambda_nm == 0.0

test("solver default => no extras", test_solver_default_no_extras)
test("solver link-budget => higher loss", test_solver_link_budget_extras)
test("solver background => augmented dark count", test_solver_background_dark_count)
test("solver API backward compat", test_solver_new_fields_optional)
test("solver API with link-budget fields", test_solver_api_with_link_budget)
test("SolveRequest new field defaults", test_solver_model_new_defaults)


# ========================================================================
# SUMMARY
# ========================================================================
print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
print(f"  PASSED: {PASS}")
print(f"  FAILED: {FAIL}")
print(f"  TOTAL:  {PASS + FAIL}")
if ERRORS:
    print(f"\n  Failed tests:")
    for name, err, _ in ERRORS:
        print(f"    - {name}: {err}")
print(f"{'='*60}")
sys.exit(1 if FAIL > 0 else 0)
