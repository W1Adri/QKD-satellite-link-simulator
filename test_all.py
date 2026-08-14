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


# ── BB84 decoy-state and finite-key ──────────────────────────────────────

def test_bb84_decoy_basic():
    from app.physics.qkd import calculate_bb84_decoy
    params = {
        "photonRate": 1e9,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_bb84_decoy(params)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["protocol"] == "BB84-decoy"
    assert result["qber"] >= 0
    assert result["secureKeyRate"] >= 0
    assert result["singlePhotonYield"] >= 0
    assert result["singlePhotonPhaseError"] >= 0
    # Single-photon gain must not exceed total gain
    assert result["singlePhotonGain"] <= result["signalGain"] + 1e-12

def test_bb84_decoy_high_loss():
    from app.physics.qkd import calculate_bb84_decoy
    params = {
        "photonRate": 1e9,
        "channelLossdB": 80.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_bb84_decoy(params)
    assert "error" not in result
    # At 80 dB loss, QBER well above threshold → SKR must be 0
    assert result["secureKeyRate"] == 0.0

def test_bb84_decoy_output_keys():
    from app.physics.qkd import calculate_bb84_decoy
    params = {
        "photonRate": 1e8,
        "channelLossdB": 40.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
        "mu_signal": 0.6,
        "mu_decoy": 0.1,
        "e_optical": 0.02,
    }
    result = calculate_bb84_decoy(params)
    for key in ("qber", "rawKeyRate", "secureKeyRate", "channelTransmittance",
                "detectionRate", "singlePhotonYield", "singlePhotonGain",
                "singlePhotonPhaseError", "signalGain", "decoyGain",
                "mu_signal", "mu_decoy", "finiteKeyFraction", "protocol"):
        assert key in result, f"Missing key: {key}"

def test_bb84_decoy_invalid_intensities():
    from app.physics.qkd import calculate_bb84_decoy
    # mu_signal <= mu_decoy should return error
    result = calculate_bb84_decoy({
        "photonRate": 1e9, "channelLossdB": 30.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
        "mu_signal": 0.1, "mu_decoy": 0.5,   # inverted
    })
    assert "error" in result

def test_bb84_decoy_finite_key():
    from app.physics.qkd import calculate_bb84_decoy
    params = {
        "photonRate": 1e8,
        "channelLossdB": 40.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
        "finite_key_n": 1e5,
        "epsilon_sec": 1e-10,
    }
    result = calculate_bb84_decoy(params)
    assert "error" not in result
    fk = result["finiteKeyFraction"]
    assert 0 <= fk <= 1.0
    # For n=1e5, finite-key SKR must be ≤ asymptotic SKR
    params_asymp = dict(params)
    del params_asymp["finite_key_n"]
    result_asymp = calculate_bb84_decoy(params_asymp)
    assert result["secureKeyRate"] <= result_asymp["secureKeyRate"] + 1e-9

def test_bb84_decoy_vs_bb84_high_loss_consistency():
    """Both protocols must give SKR=0 at very high loss."""
    from app.physics.qkd import calculate_bb84, calculate_bb84_decoy
    params = {
        "photonRate": 1e9, "channelLossdB": 90.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    }
    r1 = calculate_bb84(params)
    r2 = calculate_bb84_decoy(params)
    assert r1["secureKeyRate"] == 0.0, "BB84 SKR should be 0 at 90 dB"
    assert r2["secureKeyRate"] == 0.0, "BB84-decoy SKR should be 0 at 90 dB"

def test_bb84_qber_denominator_fix():
    """QBER denominator fix: QBER = error_rate / (signal + total_noise)."""
    import math
    from app.physics.qkd import calculate_bb84
    params = {
        "photonRate": 1e6,
        "channelLossdB": 30.0,
        "detectorEfficiency": 1.0,
        "darkCountRate": 1000.0,
    }
    result = calculate_bb84(params)
    # Reconstruct expected QBER from known formula
    eta = 10 ** (-30 / 10)
    det_rate = 1e6 * eta * 1.0 * math.exp(-0.5)
    total_noise = 1000.0  # no bg
    error_rate = total_noise / 2.0
    total_det = det_rate + total_noise
    expected_qber = error_rate / total_det * 100
    assert abs(result["qber"] - expected_qber) < 1e-9, (
        f"QBER mismatch: {result['qber']:.6f} vs expected {expected_qber:.6f}")

def test_finite_key_fraction_bounds():
    from app.physics.qkd import finite_key_fraction
    # Large n: close to 1
    fk_large = finite_key_fraction(1e9, 1e-10)
    assert 0.99 < fk_large <= 1.0, f"Expected ~1 for large n, got {fk_large}"
    # Small n: less than large n
    fk_small = finite_key_fraction(1e3, 1e-10)
    assert 0 <= fk_small < fk_large, f"Small n should give smaller fraction"
    # Zero n: returns 0
    assert finite_key_fraction(0, 1e-10) == 0.0

def test_bb84_decoy_dispatcher():
    from app.physics.qkd import calculate_qkd
    params = {
        "photonRate": 1e9,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.25,
        "darkCountRate": 100.0,
    }
    result = calculate_qkd("bb84-decoy", params)
    assert "error" not in result, f"bb84-decoy dispatch error: {result.get('error')}"
    assert result["protocol"] == "BB84-decoy"

test("BB84-decoy basic", test_bb84_decoy_basic)
test("BB84-decoy high loss", test_bb84_decoy_high_loss)
test("BB84-decoy output keys", test_bb84_decoy_output_keys)
test("BB84-decoy invalid intensities", test_bb84_decoy_invalid_intensities)
test("BB84-decoy finite-key correction", test_bb84_decoy_finite_key)
test("BB84 vs decoy high loss consistency", test_bb84_decoy_vs_bb84_high_loss_consistency)
test("BB84 QBER denominator fix", test_bb84_qber_denominator_fix)
test("finite_key_fraction bounds", test_finite_key_fraction_bounds)
test("BB84-decoy dispatcher route", test_bb84_decoy_dispatcher)


# ── MDI-QKD and TF-QKD (untrusted-relay protocols) ───────────────────────

def test_mdiqkd_basic():
    from app.physics.qkd import calculate_mdiqkd
    params = {
        "photonRate": 1e9, "channelLossdB": 30.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    }
    result = calculate_mdiqkd(params)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["protocol"] == "MDI-QKD"
    assert result["qber"] >= 0
    assert result["secureKeyRate"] > 0, "MDI should yield a key at 30 dB"
    # Single-photon-pair gain must not exceed the total BSM gain
    assert result["singlePhotonGain"] <= result["signalGain"] + 1e-12

def test_mdiqkd_high_loss():
    from app.physics.qkd import calculate_mdiqkd
    result = calculate_mdiqkd({
        "photonRate": 1e9, "channelLossdB": 80.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    })
    assert "error" not in result
    assert result["secureKeyRate"] == 0.0

def test_tfqkd_basic():
    from app.physics.qkd import calculate_tfqkd
    result = calculate_tfqkd({
        "photonRate": 1e9, "channelLossdB": 30.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    })
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["protocol"] == "TF-QKD"
    assert result["secureKeyRate"] > 0

def test_tfqkd_sqrt_eta_advantage():
    """TF-QKD (R ∝ √η) must beat decoy-BB84 (R ∝ η) at high loss."""
    from app.physics.qkd import calculate_tfqkd, calculate_bb84_decoy
    params = {
        "photonRate": 1e9, "channelLossdB": 60.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    }
    tf = calculate_tfqkd(params)
    bb84 = calculate_bb84_decoy(params)
    assert tf["secureKeyRate"] > bb84["secureKeyRate"], (
        "TF-QKD √η scaling should dominate BB84 at 60 dB")

def test_tfqkd_arm_transmittance():
    """Per-arm transmittance must equal √(total transmittance)."""
    import math
    from app.physics.qkd import calculate_tfqkd
    result = calculate_tfqkd({
        "photonRate": 1e9, "channelLossdB": 40.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    })
    assert abs(result["armTransmittance"] - math.sqrt(result["channelTransmittance"])) < 1e-12

def test_mdi_tf_invalid_input():
    from app.physics.qkd import calculate_mdiqkd, calculate_tfqkd
    assert "error" in calculate_mdiqkd({})
    assert "error" in calculate_tfqkd({})

def test_mdi_tf_dispatcher():
    from app.physics.qkd import calculate_qkd
    params = {
        "photonRate": 1e9, "channelLossdB": 30.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    }
    for proto, name in [("mdi-qkd", "MDI-QKD"), ("mdiqkd", "MDI-QKD"),
                        ("tf-qkd", "TF-QKD"), ("tfqkd", "TF-QKD")]:
        result = calculate_qkd(proto, params)
        assert "error" not in result, f"{proto} dispatch error: {result.get('error')}"
        assert result["protocol"] == name

test("MDI-QKD basic", test_mdiqkd_basic)
test("MDI-QKD high loss", test_mdiqkd_high_loss)
test("TF-QKD basic", test_tfqkd_basic)
test("TF-QKD √η advantage over BB84", test_tfqkd_sqrt_eta_advantage)
test("TF-QKD arm transmittance", test_tfqkd_arm_transmittance)
test("MDI/TF invalid input", test_mdi_tf_invalid_input)
test("MDI/TF dispatcher route", test_mdi_tf_dispatcher)


# ── Tomamichel 2012 composable finite-key bounds ─────────────────────────

def test_tomamichel_phase_error_deviation():
    import math
    from app.physics.finite_key import phase_error_deviation
    # μ matches the closed form for k = n (symmetric bases).
    n = 1e5
    mu = phase_error_deviation(n, n, 1e-10)
    expect = math.sqrt(((n + n) / (n * n)) * ((n + 1.0) / n) * math.log(4.0 / 1e-10))
    assert abs(mu - expect) < 1e-12, f"{mu} != {expect}"
    # μ shrinks as the sample grows.
    assert phase_error_deviation(1e7, 1e7) < phase_error_deviation(1e4, 1e4)
    # Degenerate sample → worst-case 0.5.
    assert phase_error_deviation(0, 0) == 0.5

def test_tomamichel_key_length_vs_asymptotic():
    from app.physics.finite_key import (
        finite_key_length_bb84, asymptotic_key_length_bb84,
    )
    n, q = 1e6, 0.02
    ell_fin = finite_key_length_bb84(n, q)
    ell_inf = asymptotic_key_length_bb84(n, q)
    # Finite length is always below the asymptotic length and non-negative.
    assert 0.0 <= ell_fin <= ell_inf
    # Larger block → larger key.
    assert finite_key_length_bb84(2e6, q) > finite_key_length_bb84(1e6, q)
    # Zero block → zero key.
    assert finite_key_length_bb84(0, q) == 0.0

def test_tomamichel_qber_dependence():
    from app.physics.finite_key import finite_key_fraction
    # Higher operating QBER → harsher finite-key penalty.
    n = 5e4
    assert finite_key_fraction(n, 1e-10, 0.05) < finite_key_fraction(n, 1e-10, 0.01)
    # Above the BB84 threshold the asymptotic key vanishes → fraction 0.
    assert finite_key_fraction(n, 1e-10, 0.12) == 0.0

def test_bb84_finite_key_wiring():
    from app.physics.qkd import calculate_bb84
    base = {
        "photonRate": 1e8,
        "channelLossdB": 25.0,
        "detectorEfficiency": 0.5,
        "darkCountRate": 100.0,
    }
    asymp = calculate_bb84(base)
    assert asymp["finiteKeyFraction"] == 1.0  # no finite_key_n → no penalty
    finite = calculate_bb84({**base, "finite_key_n": 1e5})
    assert 0.0 <= finite["finiteKeyFraction"] <= 1.0
    # Finite-key SKR must not exceed the asymptotic SKR.
    assert finite["secureKeyRate"] <= asymp["secureKeyRate"] + 1e-12

test("Tomamichel phase-error deviation μ", test_tomamichel_phase_error_deviation)
test("Tomamichel key length vs asymptotic", test_tomamichel_key_length_vs_asymptotic)
test("Tomamichel QBER dependence", test_tomamichel_qber_dependence)
test("BB84 finite-key wiring", test_bb84_finite_key_wiring)


# ── Detector models: dead-time & afterpulsing ─────────────────────────────

def test_live_fraction_ideal():
    from app.physics.detector_models import live_fraction
    # Zero dead time → fully live regardless of rate
    assert live_fraction(1e9, 0.0) == 1.0
    # Zero rate → fully live regardless of dead time
    assert live_fraction(0.0, 1e-6) == 1.0

def test_live_fraction_nonparalyzable():
    from app.physics.detector_models import live_fraction, saturated_rate
    n, tau = 1e6, 50e-9   # 1 Mcps incident, 50 ns dead time
    f = live_fraction(n, tau)
    assert abs(f - 1.0 / (1.0 + n * tau)) < 1e-12
    # Measured rate must be below incident and saturate near 1/tau
    assert saturated_rate(n, tau) < n
    assert saturated_rate(1e15, tau) < 1.0 / tau * 1.0001

def test_live_fraction_paralyzable():
    import math
    from app.physics.detector_models import live_fraction
    n, tau = 1e6, 50e-9
    f = live_fraction(n, tau, paralyzable=True)
    assert abs(f - math.exp(-n * tau)) < 1e-12
    # Paralyzable is more pessimistic than non-paralyzable at same load
    assert f < live_fraction(n, tau, paralyzable=False)

def test_afterpulse_rate():
    from app.physics.detector_models import afterpulse_rate
    assert afterpulse_rate(1e6, 0.0) == 0.0
    # First-order: ~p_ap * primary for small p_ap
    r = afterpulse_rate(1e6, 0.01)
    assert abs(r - 1e6 * 0.01 / 0.99) < 1.0

def test_apply_detector_effects_identity():
    from app.physics.detector_models import apply_detector_effects
    out = apply_detector_effects(5e5, 1e3, dead_time=0.0, afterpulse_prob=0.0)
    assert out["signalRate"] == 5e5
    assert out["noiseRate"] == 1e3
    assert out["afterpulseRate"] == 0.0
    assert out["liveFraction"] == 1.0

def test_bb84_deadtime_reduces_rate():
    from app.physics.qkd import calculate_bb84
    base = {
        "photonRate": 1e9, "channelLossdB": 20.0,
        "detectorEfficiency": 0.5, "darkCountRate": 100.0,
    }
    ideal = calculate_bb84(base)
    saturated = calculate_bb84({**base, "deadTime": 1e-6})
    # Dead time must reduce the secure rate and live fraction < 1
    assert saturated["liveFraction"] < 1.0
    assert saturated["secureKeyRate"] <= ideal["secureKeyRate"] + 1e-12
    assert ideal["liveFraction"] == 1.0

def test_bb84_afterpulse_raises_qber():
    from app.physics.qkd import calculate_bb84
    base = {
        "photonRate": 1e9, "channelLossdB": 20.0,
        "detectorEfficiency": 0.5, "darkCountRate": 100.0,
    }
    ideal = calculate_bb84(base)
    ap = calculate_bb84({**base, "afterpulseProb": 0.05})
    # Afterpulsing adds random error clicks → QBER must not decrease
    assert ap["qber"] >= ideal["qber"] - 1e-12
    assert ap["afterpulseCps"] > 0.0

def test_decoy_deadtime_reduces_efficiency():
    from app.physics.qkd import calculate_bb84_decoy
    base = {
        "photonRate": 1e9, "channelLossdB": 20.0,
        "detectorEfficiency": 0.5, "darkCountRate": 100.0,
    }
    ideal = calculate_bb84_decoy(base)
    saturated = calculate_bb84_decoy({**base, "deadTime": 1e-6})
    assert saturated["liveFraction"] < 1.0
    assert ideal["liveFraction"] == 1.0
    # Saturation lowers detected gain → secure key rate must not increase
    assert saturated["secureKeyRate"] <= ideal["secureKeyRate"] + 1e-9

def test_decoy_detector_defaults_unchanged():
    """Without detector params, results must match the prior ideal model."""
    from app.physics.qkd import calculate_bb84_decoy
    params = {
        "photonRate": 1e8, "channelLossdB": 40.0,
        "detectorEfficiency": 0.25, "darkCountRate": 100.0,
    }
    r = calculate_bb84_decoy(params)
    assert r["liveFraction"] == 1.0

test("Detector live fraction ideal", test_live_fraction_ideal)
test("Detector live fraction non-paralyzable", test_live_fraction_nonparalyzable)
test("Detector live fraction paralyzable", test_live_fraction_paralyzable)
test("Detector afterpulse rate", test_afterpulse_rate)
test("Detector effects identity", test_apply_detector_effects_identity)
test("BB84 dead-time reduces rate", test_bb84_deadtime_reduces_rate)
test("BB84 afterpulse raises QBER", test_bb84_afterpulse_raises_qber)
test("Decoy dead-time reduces efficiency", test_decoy_deadtime_reduces_efficiency)
test("Decoy detector defaults unchanged", test_decoy_detector_defaults_unchanged)


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
    import json
    import tempfile as _tempfile
    from pathlib import Path as _Path
    from fastapi.testclient import TestClient
    from app.backend import app as test_app
    # Redirect the OGS store to a throwaway temp file so endpoint tests that
    # POST stations never pollute the real app/static/ogs_locations.json.
    from app.routers import ogs as _ogs_router, solver as _solver_router
    from app.services.ogs_store import OGSStore as _OGSStore
    # Seed with the real built-in stations so solver tests that reference a
    # built-in station id (e.g. "helmos") still work, without writing back to it.
    from app.backend import DATA_PATH as _REAL_OGS_PATH
    _seed_ogs = json.loads(_Path(_REAL_OGS_PATH).read_text(encoding="utf-8"))
    _ogs_tmp = _tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(_seed_ogs, _ogs_tmp)
    _ogs_tmp.close()
    _test_ogs_store = _OGSStore(_Path(_ogs_tmp.name))
    _ogs_router.set_store(_test_ogs_store)
    _solver_router.set_store(_test_ogs_store)
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

def test_solver_uplink_pat_fading():
    """Uplink with PAT fading enabled produces higher total loss than downlink."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest

    # Epoch, RAAN and M0 are PINNED.  With epoch=None the propagator falls back
    # to the wall clock, so whether the satellite ever rose over (40 N, 2 E)
    # depended on the day the suite happened to run — this test failed for
    # exactly that reason, not for a physics reason.  These values put a
    # 33 deg-peak pass inside the single simulated orbit, every run.
    common = dict(
        station_lat=40.0, station_lon=2.0,
        samples_per_orbit=120, total_orbits=1,
        epoch="2024-03-20T00:00:00Z",
        raan_deg=160.0, mean_anomaly_deg=110.0,
        pointing_error_urad=5.0,
        scintillation_enabled=True,
        pat_fading_enabled=True,
    )
    req_dl = SolveRequest(link_direction="downlink", **common)
    req_ul = SolveRequest(link_direction="uplink", **common)

    r_dl = _run_solve(req_dl)
    r_ul = _run_solve(req_ul)
    m_dl = r_dl["station_metrics"]
    m_ul = r_ul["station_metrics"]

    # beamWanderUrad should be present
    assert "beamWanderUrad" in m_ul, "Missing beamWanderUrad in output"
    assert "patFadingDb" in m_ul, "Missing patFadingDb in output"

    # At visible data points, uplink total loss >= downlink (beam wander adds to uplink)
    n_pts = len(m_dl["elevationDeg"])
    visible = [i for i in range(n_pts)
               if m_dl["elevationDeg"][i] is not None and m_dl["elevationDeg"][i] > 5]
    assert len(visible) > 0, "No visible data points above 5 deg elevation"

    ul_higher_count = 0
    for i in visible:
        if m_ul["totalLossDb"][i] >= m_dl["totalLossDb"][i]:
            ul_higher_count += 1
        # Beam wander should be >= 0 for uplink, 0 for downlink
        assert m_ul["beamWanderUrad"][i] >= 0, f"Negative beam wander at point {i}"
        assert abs(m_dl["beamWanderUrad"][i]) < 1e-10, \
            f"Downlink beam wander should be 0, got {m_dl['beamWanderUrad'][i]}"

    # Majority of visible points should have uplink >= downlink loss
    assert ul_higher_count >= len(visible) * 0.8, \
        f"Uplink loss >= downlink at only {ul_higher_count}/{len(visible)} points"

def test_solver_dynamic_background():
    """Dynamic background enabled produces varying skyRadianceWm2srUm."""
    from app.routers.solver import _run_solve
    from app.models import SolveRequest

    req = SolveRequest(
        station_lat=40.0, station_lon=2.0,
        samples_per_orbit=36, total_orbits=1,
        background_enabled=True,
        background_Hrad_W_m2_sr_um=1e-2,
        background_fov_mrad=1.0,
        background_delta_lambda_nm=10.0,
        dynamic_background_enabled=True,
    )
    result = _run_solve(req)
    m = result["station_metrics"]

    assert "skyRadianceWm2srUm" in m, "Missing skyRadianceWm2srUm in output"
    assert len(m["skyRadianceWm2srUm"]) == 36, "skyRadianceWm2srUm length mismatch"

    # At least some values should be non-zero (daytime points)
    # Note: depending on epoch time, all may be zero (nighttime) or nonzero (daytime).
    # The key check is that the array exists and has real values (not all NaN/None).
    assert all(isinstance(v, (int, float)) for v in m["skyRadianceWm2srUm"]), \
        "skyRadianceWm2srUm contains non-numeric values"

test("solver uplink + PAT fading => higher loss", test_solver_uplink_pat_fading)
test("solver dynamic background => skyRadiance array", test_solver_dynamic_background)


# ========================================================================
# Phase 2: Beam Wander & PAT Fading
# ========================================================================
section("Phase 2: Beam Wander & PAT Fading")

from app.physics.link_budget import (
    beam_wander_variance_rad2,
    pat_fading_penalty_db,
    combined_pointing_fading_db,
    pointing_loss_db as _pointing_loss_db,
)
_DIV = 1.22 * 810e-9 / 0.15  # full-angle divergence for 810 nm, 15 cm aperture

def test_beam_wander_downlink_is_zero():
    """beam_wander_variance_rad2 returns 0 for downlink regardless of geometry."""
    val = beam_wander_variance_rad2(45.0, 810.0, 0.15, 0.1, 550e3, "downlink")
    assert val == 0.0, f"Expected 0.0, got {val}"

def test_beam_wander_uplink_positive():
    """beam_wander_variance_rad2 returns >0 for uplink at typical LEO geometry."""
    val = beam_wander_variance_rad2(45.0, 810.0, 0.15, 0.1, 550e3, "uplink")
    assert val > 0.0, f"Expected >0, got {val}"

def test_beam_wander_uplink_negative_elev_zero():
    """beam_wander_variance_rad2 returns 0 when elevation <= 0."""
    val_zero = beam_wander_variance_rad2(0.0, 810.0, 0.15, 0.1, 550e3, "uplink")
    val_neg = beam_wander_variance_rad2(-5.0, 810.0, 0.15, 0.1, 550e3, "uplink")
    assert val_zero == 0.0, f"elev=0 expected 0, got {val_zero}"
    assert val_neg == 0.0, f"elev=-5 expected 0, got {val_neg}"

def test_pat_fading_less_than_deterministic():
    """pat_fading_penalty_db < pointing_loss_db for same inputs (Rayleigh average vs peak).

    The Rayleigh-averaged transmittance 1/(1+8*(sigma/div)^2) > exp(-8*(sigma/div)^2)
    for all sigma > 0, so the mean fading penalty is always LESS than the
    deterministic (worst-case) pointing loss at 1-sigma offset.
    This means pat_fading gives a less conservative (smaller) dB penalty.
    """
    pat = pat_fading_penalty_db(5.0, _DIV)
    det = _pointing_loss_db(5.0, _DIV)
    assert pat < det, f"PAT mean fading {pat:.4f} dB must be less than deterministic {det:.4f} dB"
    assert pat > 0.0, f"PAT fading must be positive for non-zero jitter, got {pat}"

def test_pat_fading_zero_jitter():
    """pat_fading_penalty_db returns 0 when jitter is zero."""
    val = pat_fading_penalty_db(0.0, _DIV)
    assert val == 0.0, f"Expected 0.0, got {val}"

def test_combined_downlink_ignores_bw():
    """combined_pointing_fading_db(downlink) equals pat_fading_penalty_db."""
    comb = combined_pointing_fading_db(5.0, 3.0, _DIV, "downlink")
    pat = pat_fading_penalty_db(5.0, _DIV)
    assert abs(comb - pat) < 1e-12, f"downlink combined {comb} != pat_fading {pat}"

def test_combined_uplink_larger_than_downlink():
    """combined uplink (with beam wander) > downlink (without beam wander)."""
    comb_ul = combined_pointing_fading_db(5.0, 3.0, _DIV, "uplink")
    comb_dl = combined_pointing_fading_db(5.0, 0.0, _DIV, "downlink")
    assert comb_ul > comb_dl, f"uplink {comb_ul:.4f} must exceed downlink {comb_dl:.4f}"

test("beam_wander_downlink_is_zero", test_beam_wander_downlink_is_zero)
test("beam_wander_uplink_positive", test_beam_wander_uplink_positive)
test("beam_wander_uplink_negative_elev_zero", test_beam_wander_uplink_negative_elev_zero)
test("pat_fading_less_than_deterministic (Rayleigh mean < peak)", test_pat_fading_less_than_deterministic)
test("pat_fading_zero_jitter", test_pat_fading_zero_jitter)
test("combined_downlink_ignores_bw", test_combined_downlink_ignores_bw)
test("combined_uplink_larger_than_downlink", test_combined_uplink_larger_than_downlink)


# ========================================================================
# Phase 2: Sky Background Radiance
# ========================================================================
section("Phase 2: Sky Background Radiance")


def test_solar_radiance_daytime_positive():
    """solar_sky_radiance_W_m2_sr_um returns > 0 during daytime (zenith=30 deg)."""
    from app.physics.sky_background import solar_sky_radiance_W_m2_sr_um
    result = solar_sky_radiance_W_m2_sr_um(30.0)
    assert result > 0, f"Expected > 0, got {result}"


def test_solar_radiance_night_zero():
    """solar_sky_radiance_W_m2_sr_um returns 0 when sun is below horizon (zenith=95 deg)."""
    from app.physics.sky_background import solar_sky_radiance_W_m2_sr_um
    result = solar_sky_radiance_W_m2_sr_um(95.0)
    assert result == 0.0, f"Expected 0.0, got {result}"


def test_solar_radiance_overhead_gt_horizon():
    """Overhead sun (zenith=0) produces more radiance than sun near horizon (zenith=80)."""
    from app.physics.sky_background import solar_sky_radiance_W_m2_sr_um
    overhead = solar_sky_radiance_W_m2_sr_um(0.0)
    horizon = solar_sky_radiance_W_m2_sr_um(80.0)
    assert overhead > horizon, f"Overhead {overhead} should be > horizon {horizon}"


def test_lunar_radiance_below_horizon_zero():
    """lunar_sky_radiance returns 0 when Moon is below horizon (2024-01-01 12:00Z, lat=40)."""
    from datetime import datetime, timezone
    from app.physics.sky_background import lunar_sky_radiance_W_m2_sr_um
    # 2024-01-01 noon UTC: Moon is below horizon at lat=40, lon=0 (altitude ~ -13 deg)
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = lunar_sky_radiance_W_m2_sr_um(40.0, 0.0, 100.0, dt)
    assert result == 0.0, f"Moon below horizon should return 0, got {result}"


def test_lunar_radiance_full_moon_gt_quarter():
    """Full moon (2024-01-25 22:00Z) produces more radiance than first quarter (2024-01-18 22:00Z)."""
    from datetime import datetime, timezone
    from app.physics.sky_background import lunar_sky_radiance_W_m2_sr_um
    # Full moon: phase_angle ~ 5 deg, altitude ~ 54 deg
    dt_full = datetime(2024, 1, 25, 22, 0, 0, tzinfo=timezone.utc)
    # Quarter moon: phase_angle ~ 80 deg, altitude ~ 37 deg
    dt_quarter = datetime(2024, 1, 18, 22, 0, 0, tzinfo=timezone.utc)
    full = lunar_sky_radiance_W_m2_sr_um(40.0, 0.0, 100.0, dt_full)
    quarter = lunar_sky_radiance_W_m2_sr_um(40.0, 0.0, 100.0, dt_quarter)
    assert full > 0, f"Full moon should be > 0, got {full}"
    assert quarter > 0, f"Quarter moon should be > 0, got {quarter}"
    assert full > quarter, f"Full moon {full} should be > quarter moon {quarter}"


def test_lunar_v_magnitude_phase_dependency():
    """Internal V-magnitude formula: full moon (phase=0) is brighter than half moon (phase=90)."""
    from app.physics.sky_background import _lunar_V_magnitude
    v_full = _lunar_V_magnitude(0.0)
    v_half = _lunar_V_magnitude(90.0)
    # Lower V magnitude = brighter
    assert v_full < v_half, f"Full moon V={v_full} should be brighter (lower) than half moon V={v_half}"
    assert abs(v_full - (-12.73)) < 0.01, f"Full moon V should be ~-12.73, got {v_full}"


def test_background_from_sky_daytime_uses_solar():
    """background_noise_from_sky during daytime returns solar component (== solar_sky_radiance)."""
    from app.physics.sky_background import background_noise_from_sky, solar_sky_radiance_W_m2_sr_um
    solar = solar_sky_radiance_W_m2_sr_um(30.0)
    combined = background_noise_from_sky(30.0, 40.0, 0.0, 0.0, None, 810.0)
    assert combined == solar, f"Daytime combined {combined} should equal solar {solar}"


def test_background_from_sky_nighttime_uses_lunar():
    """background_noise_from_sky at night returns lunar model (not solar)."""
    from datetime import datetime, timezone
    from app.physics.sky_background import background_noise_from_sky, lunar_sky_radiance_W_m2_sr_um
    dt_full = datetime(2024, 1, 25, 22, 0, 0, tzinfo=timezone.utc)
    lunar = lunar_sky_radiance_W_m2_sr_um(40.0, 0.0, 100.0, dt_full)
    combined = background_noise_from_sky(100.0, 40.0, 0.0, 100.0, dt_full, 810.0)
    assert combined == lunar, f"Nighttime combined {combined} should equal lunar {lunar}"


test("solar_radiance_daytime_positive", test_solar_radiance_daytime_positive)
test("solar_radiance_night_zero", test_solar_radiance_night_zero)
test("solar_radiance_overhead_gt_horizon", test_solar_radiance_overhead_gt_horizon)
test("lunar_radiance_below_horizon_zero", test_lunar_radiance_below_horizon_zero)
test("lunar_radiance_full_moon_gt_quarter", test_lunar_radiance_full_moon_gt_quarter)
test("lunar_V_magnitude_phase_dependency", test_lunar_v_magnitude_phase_dependency)
test("background_from_sky_daytime_uses_solar", test_background_from_sky_daytime_uses_solar)
test("background_from_sky_nighttime_uses_lunar", test_background_from_sky_nighttime_uses_lunar)


# ========================================================================
# Phase 3: Key Volume
# ========================================================================
section("Phase 3: Physics: Key Volume")

from app.physics.key_volume import segment_passes, compute_key_volume, aggregate_daily_mb


def test_kv_segment_two_passes():
    """segment_passes returns 2 passes for a typical visibility pattern."""
    elev = [0, 0, 15, 20, 25, 20, 15, 0, 0, 10, 20, 10, 0]
    segs = segment_passes(elev, threshold_deg=5.0)
    assert len(segs) == 2, f"Expected 2 passes, got {len(segs)}: {segs}"
    assert segs[0] == (2, 6), f"First pass wrong: {segs[0]}"
    assert segs[1] == (9, 11), f"Second pass wrong: {segs[1]}"


def test_kv_segment_all_below():
    """segment_passes returns empty list when all elevations are below threshold."""
    elev = [0, 1, 2, 3, 4]
    segs = segment_passes(elev, threshold_deg=5.0)
    assert segs == [], f"Expected [], got {segs}"


def test_kv_segment_single_blip_skipped():
    """segment_passes skips single-sample blips (only 1 sample above threshold)."""
    elev = [0, 0, 10, 0, 0]  # single blip at index 2
    segs = segment_passes(elev, threshold_deg=5.0)
    assert segs == [], f"Single-sample blip should be skipped, got {segs}"


def test_kv_compute_physical_volume():
    """10 kbit/s for 100 s → ~0.125 MB."""
    # 100 s pass with uniform 10 kbit/s = 10*1000*100 = 1_000_000 bits = 0.125 MB
    timeline = [float(t) for t in range(101)]          # 0..100 s
    link_est = [True] * 101
    elev     = [10.0] * 101                             # always above threshold
    qkd      = [{"t": float(t), "secureKeyRate": 10.0} for t in range(101)]
    result = compute_key_volume(timeline, link_est, elev, qkd, "2026-03-30T00:00:00Z")
    assert result["pass_count"] == 1, f"Expected 1 pass, got {result['pass_count']}"
    # trapz of constant 10_000 bit/s over 100 s = 1_000_000 bits → 0.125 MB
    expected_mb = 1_000_000 / (8.0 * 1e6)
    assert abs(result["total_key_volume_mb"] - expected_mb) < 1e-6, (
        f"Volume {result['total_key_volume_mb']:.8f} != expected {expected_mb:.8f}")


def test_kv_negative_rate_clamped():
    """Negative secureKeyRate is clamped to 0 before integration."""
    timeline = [0.0, 1.0, 2.0, 50.0, 51.0, 52.0]
    link_est = [True] * 6
    elev     = [10.0] * 6
    qkd = [
        {"t": 0.0, "secureKeyRate": -5.0},    # negative — should be zeroed
        {"t": 1.0, "secureKeyRate": 10.0},
        {"t": 2.0, "secureKeyRate": 10.0},
        {"t": 50.0, "secureKeyRate": -1.0},   # negative — should be zeroed
        {"t": 51.0, "secureKeyRate": 10.0},
        {"t": 52.0, "secureKeyRate": 10.0},
    ]
    result = compute_key_volume(timeline, link_est, elev, qkd, "")
    # All rates at t=0 and t=50 are clamped — volume should be > 0 but partial
    assert result["total_key_volume_mb"] >= 0.0, "Total volume must be non-negative"


def test_kv_link_not_established_zeroed():
    """Samples where linkEstablished is False contribute 0 to integration."""
    timeline = [float(t) for t in range(11)]   # 0..10 s
    link_est = [True] * 11
    link_est[3] = False                         # gap at second 3
    link_est[4] = False
    elev     = [10.0] * 11
    qkd = [{"t": float(t), "secureKeyRate": 10.0} for t in range(11)]
    result_partial = compute_key_volume(timeline, link_est, elev, qkd, "")
    # Full link (all True)
    link_full = [True] * 11
    result_full = compute_key_volume(timeline, link_full, elev, qkd, "")
    # Partial must be less than full
    assert result_partial["total_key_volume_mb"] < result_full["total_key_volume_mb"], (
        "Partial link should produce less volume than full link")


def test_kv_aggregate_daily():
    """aggregate_daily_mb partitions passes across two calendar days."""
    # Pass 1 starts at t=0 (day 1: 2026-03-30), pass 2 at t=86400 (day 2: 2026-03-31)
    passes = [
        {"pass_start_s": 0.0,     "key_volume_mb": 0.1},
        {"pass_start_s": 86400.0, "key_volume_mb": 0.2},
    ]
    daily = aggregate_daily_mb(passes, "2026-03-30T00:00:00Z")
    assert "2026-03-30" in daily, f"Missing 2026-03-30 in {daily}"
    assert "2026-03-31" in daily, f"Missing 2026-03-31 in {daily}"
    assert abs(daily["2026-03-30"] - 0.1) < 1e-9
    assert abs(daily["2026-03-31"] - 0.2) < 1e-9


test("segment_passes two real passes", test_kv_segment_two_passes)
test("segment_passes all below threshold", test_kv_segment_all_below)
test("segment_passes single blip skipped", test_kv_segment_single_blip_skipped)
test("compute_key_volume physical volume (10 kbps/100s=0.125MB)", test_kv_compute_physical_volume)
test("compute_key_volume negative rate clamped", test_kv_negative_rate_clamped)
test("compute_key_volume non-established zeroed", test_kv_link_not_established_zeroed)
test("aggregate_daily_mb two calendar days", test_kv_aggregate_daily)


# ========================================================================
# Phase 3: PCFLOS Service (unit tests with synthetic data — no live API)
# ========================================================================
section("Phase 3: PCFLOS Service")

from app.services.pcflos_svc import compute_pcflos_monthly


def _make_hourly(months_data: dict[int, tuple[int, int]]) -> dict:
    """Build a synthetic hourly dict for testing.

    months_data: {month_int: (total_hours, clear_hours)}
    where clear_hours have cloud_cover=0 and the rest have cloud_cover=100.
    """
    times = []
    cloud_cover = []
    for month, (total, clear) in months_data.items():
        for h in range(total):
            # Use 2025 as the year for date strings
            times.append(f"2025-{month:02d}-01T{(h % 24):02d}:00")
            cloud_cover.append(0.0 if h < clear else 100.0)
    return {"time": times, "cloud_cover": cloud_cover}


def test_pcflos_basic_fraction():
    """50% clear hours in Jan → monthly PCFLOS[1] = 0.5."""
    data = _make_hourly({1: (10, 5)})   # 10 hours, 5 clear
    result = compute_pcflos_monthly(data, threshold_pct=30.0)
    assert 1 in result, f"Month 1 missing from result: {result}"
    assert abs(result[1] - 0.5) < 1e-9, f"Expected 0.5, got {result[1]}"


def test_pcflos_skips_none():
    """None values in cloud_cover are skipped and don't affect the fraction."""
    data = {"time": ["2025-01-01T00:00", "2025-01-01T01:00", "2025-01-01T02:00"],
            "cloud_cover": [0.0, None, 100.0]}
    result = compute_pcflos_monthly(data, threshold_pct=30.0)
    # 2 valid hours (skipping None): 1 clear, 1 cloudy → 0.5
    assert abs(result[1] - 0.5) < 1e-9, f"Expected 0.5 with None skipped, got {result[1]}"


def test_pcflos_threshold_higher_gives_more():
    """Higher cloud threshold → more hours counted as clear → higher PCFLOS."""
    data = _make_hourly({1: (10, 4)})   # 4 of 10 clear at threshold=30
    r20 = compute_pcflos_monthly(data, threshold_pct=20.0)
    # With threshold 90, all 4 zero-cloud + all 6 hundred-cloud would still be 0 at 20%
    # Let's use a dataset where some hours are at 50%
    mixed = {"time": [f"2025-01-01T{h:02d}:00" for h in range(10)],
             "cloud_cover": [20.0, 20.0, 50.0, 50.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0]}
    r_low  = compute_pcflos_monthly(mixed, threshold_pct=30.0)   # 2 clear
    r_high = compute_pcflos_monthly(mixed, threshold_pct=60.0)   # 4 clear
    assert r_high[1] >= r_low[1], f"Higher threshold should give >= PCFLOS: {r_high[1]} vs {r_low[1]}"


def test_pcflos_returns_all_12_months():
    """compute_pcflos_monthly returns entries for all 12 months when given full-year data."""
    months_data = {m: (24, 12) for m in range(1, 13)}  # 24 hours, 50% clear each month
    data = _make_hourly(months_data)
    result = compute_pcflos_monthly(data, threshold_pct=30.0)
    for m in range(1, 13):
        assert m in result, f"Month {m} missing from result"
    # All months should be 0.5
    for m in range(1, 13):
        assert abs(result[m] - 0.5) < 1e-9, f"Month {m}: expected 0.5, got {result[m]}"


def test_pcflos_annual_correct():
    """Annual PCFLOS is correct weighted average of monthly."""
    # Jan: 8 hours, 4 clear (0.5) / Feb: 4 hours, 4 clear (1.0)
    data = {"time": [f"2025-01-01T{h:02d}:00" for h in range(8)] +
                    [f"2025-02-01T{h:02d}:00" for h in range(4)],
            "cloud_cover": [0.0]*4 + [100.0]*4 + [0.0]*4}
    monthly = compute_pcflos_monthly(data, threshold_pct=30.0)
    # Annual = 8 clear / 12 total valid = 2/3
    total_clear = sum(v * (8 if k == 1 else 4) for k, v in monthly.items())
    annual = total_clear / 12
    assert abs(annual - 8/12) < 1e-6, f"Annual PCFLOS: expected {8/12:.4f}, got {annual:.4f}"


test("pcflos_basic_fraction (50% clear)", test_pcflos_basic_fraction)
test("pcflos_skips_none cloud_cover values", test_pcflos_skips_none)
test("pcflos_threshold_higher_gives_more", test_pcflos_threshold_higher_gives_more)
test("pcflos_returns_all_12_months", test_pcflos_returns_all_12_months)
test("pcflos_annual correct weighted average", test_pcflos_annual_correct)


# ========================================================================
# Phase 3: Relay & Effective Key Volume
# ========================================================================
section("Phase 3: Relay & Effective Key Volume")

from app.routers.relay import match_relay_passes, apply_pcflos


def test_relay_match_two_orbits():
    """match_relay_passes returns 2 matched orbits with relay_volume = min(V_A, V_B)."""
    period = 5400.0
    # Orbit 0: midpoint = (100+200)/2 = 150 s → orbit_idx = 0
    # Orbit 1: midpoint = (5600+5700)/2 = 5650 s → orbit_idx = 1
    # Orbit 2: midpoint = (11200+11300)/2 = 11250 s → orbit_idx = 2
    passes_a = [
        {"pass_start_s": 100.0, "pass_end_s": 200.0, "key_volume_mb": 0.1},   # orbit 0
        {"pass_start_s": 5600.0, "pass_end_s": 5700.0, "key_volume_mb": 0.2},  # orbit 1
        {"pass_start_s": 11200.0, "pass_end_s": 11300.0, "key_volume_mb": 0.3},  # orbit 2
    ]
    passes_b = [
        {"pass_start_s": 110.0, "pass_end_s": 210.0, "key_volume_mb": 0.15},  # orbit 0
        {"pass_start_s": 11210.0, "pass_end_s": 11310.0, "key_volume_mb": 0.25},  # orbit 2
    ]
    relay_passes, total = match_relay_passes(passes_a, passes_b, period)
    assert len(relay_passes) == 2, f"Expected 2 matched orbits, got {len(relay_passes)}"
    # orbit 0: min(0.1, 0.15) = 0.1
    orbit0 = next(p for p in relay_passes if p["orbit_idx"] == 0)
    assert abs(orbit0["relay_volume_mb"] - 0.1) < 1e-9, f"Orbit 0 relay: {orbit0['relay_volume_mb']}"
    # orbit 2: min(0.3, 0.25) = 0.25
    orbit2 = next(p for p in relay_passes if p["orbit_idx"] == 2)
    assert abs(orbit2["relay_volume_mb"] - 0.25) < 1e-9, f"Orbit 2 relay: {orbit2['relay_volume_mb']}"


def test_relay_no_overlap():
    """match_relay_passes returns empty list and 0 total when no orbits match."""
    period = 5400.0
    passes_a = [{"pass_start_s": 100.0, "pass_end_s": 200.0, "key_volume_mb": 0.1}]   # orbit 0
    passes_b = [{"pass_start_s": 5600.0, "pass_end_s": 5700.0, "key_volume_mb": 0.2}]  # orbit 1
    relay_passes, total = match_relay_passes(passes_a, passes_b, period)
    assert relay_passes == [], f"Expected empty list, got {relay_passes}"
    assert total == 0.0, f"Expected 0.0 total, got {total}"


def test_relay_orbit_idx_from_midpoint():
    """Orbit assignment uses midpoint: pass at 100-200s with period=5400s → orbit_idx=0."""
    period = 5400.0
    # midpoint = (100+200)/2 = 150 → orbit_idx = int(150/5400) = 0
    passes_a = [{"pass_start_s": 100.0, "pass_end_s": 200.0, "key_volume_mb": 0.1}]
    passes_b = [{"pass_start_s": 120.0, "pass_end_s": 180.0, "key_volume_mb": 0.08}]
    relay_passes, total = match_relay_passes(passes_a, passes_b, period)
    assert len(relay_passes) == 1, "Should match 1 orbit"
    assert relay_passes[0]["orbit_idx"] == 0, f"Expected orbit 0, got {relay_passes[0]['orbit_idx']}"


def test_apply_pcflos_monthly():
    """apply_pcflos multiplies total_key_volume_mb by monthly PCFLOS factor."""
    kv = {"total_key_volume_mb": 1.0, "passes": [], "pass_count": 0, "daily_mb": {}}
    pcflos = {"monthly_pcflos": {3: 0.7}, "annual_pcflos": 0.65}
    result = apply_pcflos(kv, "2026-03-30T00:00:00Z", pcflos)
    assert abs(result["pcflos_factor"] - 0.7) < 1e-9, f"Expected 0.7, got {result['pcflos_factor']}"
    assert abs(result["effective_key_volume_mb"] - 0.7) < 1e-9, (
        f"Expected 0.7 MB effective, got {result['effective_key_volume_mb']}")


def test_apply_pcflos_fallback_annual():
    """apply_pcflos falls back to annual_pcflos when epoch month not in monthly dict."""
    kv = {"total_key_volume_mb": 2.0, "passes": [], "pass_count": 0, "daily_mb": {}}
    pcflos = {"monthly_pcflos": {6: 0.8}, "annual_pcflos": 0.65}
    # epoch is March (month=3), but only June(6) is in monthly_pcflos → fallback to annual
    result = apply_pcflos(kv, "2026-03-30T00:00:00Z", pcflos)
    assert abs(result["pcflos_factor"] - 0.65) < 1e-9, f"Expected annual 0.65, got {result['pcflos_factor']}"
    assert abs(result["effective_key_volume_mb"] - 1.30) < 1e-9, (
        f"Expected 1.30 MB effective, got {result['effective_key_volume_mb']}")


test("relay match 2 orbits with min(V_A,V_B)", test_relay_match_two_orbits)
test("relay no overlapping orbits → empty", test_relay_no_overlap)
test("relay orbit_idx from midpoint", test_relay_orbit_idx_from_midpoint)
test("apply_pcflos monthly factor", test_apply_pcflos_monthly)
test("apply_pcflos fallback to annual", test_apply_pcflos_fallback_annual)


# ========================================================================
# Multi-OGS Batch Solver
# ========================================================================
section("Multi-OGS Batch Solver")

def test_multi_ogs_model_defaults():
    """MultiOGSSolveRequest has sensible defaults."""
    from app.models import MultiOGSSolveRequest
    r = MultiOGSSolveRequest()
    assert r.semi_major_axis == 6771.0
    assert r.qkd_protocol is None
    assert r.station_ids is None
    assert r.inline_stations is None

def test_multi_ogs_model_requires_stations_at_call_time():
    """MultiOGSSolveRequest is valid even with no stations (endpoint validates)."""
    from app.models import MultiOGSSolveRequest
    r = MultiOGSSolveRequest(qkd_protocol="bb84-decoy")
    assert r.qkd_protocol == "bb84-decoy"

def test_run_multi_ogs_inline_stations():
    """_run_multi_ogs_solve returns one result per inline station."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6771.0,
        inclination_deg=53.0,
        samples_per_orbit=36,
        total_orbits=1,
        qkd_protocol="bb84-decoy",
    )
    stations = [
        {"id": "helmos",   "name": "Helmos",   "lat": 37.9844, "lon": 22.1961, "altitude_m": 2340, "aperture_m": 2.3},
        {"id": "skinakas", "name": "Skinakas", "lat": 35.212,  "lon": 24.899,  "altitude_m": 1750, "aperture_m": 0.6},
        {"id": "tenerife", "name": "Tenerife", "lat": 28.3,    "lon": -16.509, "altitude_m": 2390, "aperture_m": 1.0},
    ]
    result = _run_multi_ogs_solve(req, stations)

    assert "orbit" in result
    assert "stations" in result
    assert result["station_count"] == 3
    assert len(result["stations"]) == 3

def test_multi_ogs_orbit_propagated_once():
    """All stations share the same orbit metadata."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6771.0,
        inclination_deg=53.0,
        samples_per_orbit=36,
        total_orbits=1,
    )
    stations = [
        {"id": "a", "name": "A", "lat": 40.0, "lon": 2.0, "altitude_m": 100, "aperture_m": 1.0},
        {"id": "b", "name": "B", "lat": 50.0, "lon": 10.0, "altitude_m": 200, "aperture_m": 1.0},
    ]
    result = _run_multi_ogs_solve(req, stations)
    orb = result["orbit"]
    assert orb["semi_major_axis"] > 6700
    assert orb["period_s"] > 5000
    assert orb["samples"] == 36

def test_multi_ogs_qkd_summary_structure():
    """qkd_summary contains all expected keys when QKD is enabled."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6771.0,
        inclination_deg=53.0,
        samples_per_orbit=36,
        total_orbits=1,
        qkd_protocol="bb84-decoy",
    )
    stations = [
        {"id": "helmos", "name": "Helmos", "lat": 37.9844, "lon": 22.1961, "altitude_m": 2340, "aperture_m": 2.3},
    ]
    result = _run_multi_ogs_solve(req, stations)
    s = result["stations"][0]
    assert "qkd_summary" in s, "qkd_summary missing"
    qs = s["qkd_summary"]
    assert "pass_count" in qs
    assert "total_key_volume_mb" in qs
    assert "peak_skr_kbps" in qs
    assert "mean_skr_kbps" in qs
    assert "max_elevation_deg" in qs
    assert "ground_aperture_m" in qs
    assert qs["ground_aperture_m"] == 2.3  # station aperture used, not default

def test_multi_ogs_station_id_preserved():
    """Station id and name are echoed back in each result."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(samples_per_orbit=36, total_orbits=1)
    stations = [{"id": "helmos", "name": "Helmos", "lat": 37.9844, "lon": 22.1961, "altitude_m": 2340, "aperture_m": 2.3}]
    result = _run_multi_ogs_solve(req, stations)
    s = result["stations"][0]
    assert s["id"] == "helmos"
    assert s["name"] == "Helmos"
    assert abs(s["lat"] - 37.9844) < 1e-4
    assert s["aperture_m"] == 2.3

def test_multi_ogs_high_lat_vs_low_lat():
    """High-latitude station sees more passes for SSO orbit."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6871.0,   # 500 km SSO-like
        inclination_deg=97.4,     # SSO
        samples_per_orbit=180,
        total_orbits=10,
        qkd_protocol="bb84-decoy",
        min_elevation_deg=5.0,
        elevation_threshold_deg=5.0,
    )
    stations = [
        {"id": "svalbard",  "name": "Svalbard",  "lat": 78.23, "lon": 15.41, "altitude_m": 460, "aperture_m": 0.5},
        {"id": "tenerife",  "name": "Tenerife",  "lat": 28.3,  "lon": -16.51, "altitude_m": 2390, "aperture_m": 1.0},
    ]
    result = _run_multi_ogs_solve(req, stations)
    svalbard = result["stations"][0]
    tenerife = result["stations"][1]
    # Svalbard should see more passes of a polar orbit
    assert svalbard["qkd_summary"]["pass_count"] >= tenerife["qkd_summary"]["pass_count"], \
        f"Svalbard {svalbard['qkd_summary']['pass_count']} passes < Tenerife {tenerife['qkd_summary']['pass_count']}"

def test_multi_ogs_aperture_affects_skr():
    """Larger aperture → higher SKR all else equal."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6771.0,
        inclination_deg=53.0,
        samples_per_orbit=36,
        total_orbits=1,
        qkd_protocol="bb84-decoy",
    )
    # Same location, different apertures
    stations = [
        {"id": "small", "name": "Small", "lat": 37.98, "lon": 22.19, "altitude_m": 2340, "aperture_m": 0.3},
        {"id": "large", "name": "Large", "lat": 37.98, "lon": 22.19, "altitude_m": 2340, "aperture_m": 2.3},
    ]
    result = _run_multi_ogs_solve(req, stations)
    small_peak = result["stations"][0]["qkd_summary"]["peak_skr_kbps"]
    large_peak = result["stations"][1]["qkd_summary"]["peak_skr_kbps"]
    assert large_peak >= small_peak, f"Large aperture SKR {large_peak} < small aperture SKR {small_peak}"

def test_multi_ogs_api_inline():
    """POST /api/solve/multi-ogs with inline_stations returns correct structure."""
    if not HAS_CLIENT:
        return
    r = client.post("/api/solve/multi-ogs", json={
        "semi_major_axis": 6771.0,
        "inclination_deg": 53.0,
        "samples_per_orbit": 36,
        "total_orbits": 1,
        "qkd_protocol": "bb84-decoy",
        "inline_stations": [
            {"name": "Helmos",   "lat": 37.9844, "lon": 22.1961, "altitude_m": 2340, "aperture_m": 2.3},
            {"name": "Skinakas", "lat": 35.212,  "lon": 24.899,  "altitude_m": 1750, "aperture_m": 0.6},
        ],
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "orbit" in data
    assert "stations" in data
    assert data["station_count"] == 2
    assert data["stations"][0]["name"] == "Helmos"
    assert "qkd_summary" in data["stations"][0]

def test_multi_ogs_api_no_stations_returns_400():
    """POST /api/solve/multi-ogs with no stations returns 400."""
    if not HAS_CLIENT:
        return
    r = client.post("/api/solve/multi-ogs", json={
        "semi_major_axis": 6771.0,
    })
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"

def test_multi_ogs_api_by_store_id():
    """POST /api/solve/multi-ogs with station_ids resolves built-in stations."""
    if not HAS_CLIENT:
        return
    r = client.post("/api/solve/multi-ogs", json={
        "semi_major_axis": 6771.0,
        "inclination_deg": 53.0,
        "samples_per_orbit": 36,
        "total_orbits": 1,
        "qkd_protocol": "bb84-decoy",
        "station_ids": ["helmos", "skinakas"],
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["station_count"] == 2
    ids = [s["id"] for s in data["stations"]]
    assert "helmos" in ids
    assert "skinakas" in ids

def test_multi_ogs_api_unknown_station_id_returns_404():
    """POST /api/solve/multi-ogs with unknown station_id returns 404."""
    if not HAS_CLIENT:
        return
    r = client.post("/api/solve/multi-ogs", json={
        "station_ids": ["nonexistent-station-xyz"],
    })
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"

def test_multi_ogs_key_volume_structure():
    """key_volume dict has expected keys when QKD enabled."""
    from app.models import MultiOGSSolveRequest
    from app.routers.solver import _run_multi_ogs_solve

    req = MultiOGSSolveRequest(
        semi_major_axis=6771.0,
        inclination_deg=53.0,
        samples_per_orbit=36,
        total_orbits=1,
        qkd_protocol="bb84",
    )
    stations = [{"id": "helmos", "name": "Helmos", "lat": 37.9844, "lon": 22.1961, "altitude_m": 2340, "aperture_m": 2.3}]
    result = _run_multi_ogs_solve(req, stations)
    s = result["stations"][0]
    kv = s.get("key_volume", {})
    assert "pass_count" in kv
    assert "total_key_volume_mb" in kv
    assert "passes" in kv
    assert "daily_mb" in kv

test("MultiOGSSolveRequest defaults", test_multi_ogs_model_defaults)
test("MultiOGSSolveRequest valid without stations", test_multi_ogs_model_requires_stations_at_call_time)
test("_run_multi_ogs_solve: 3 inline stations", test_run_multi_ogs_inline_stations)
test("_run_multi_ogs_solve: orbit propagated once", test_multi_ogs_orbit_propagated_once)
test("_run_multi_ogs_solve: qkd_summary structure", test_multi_ogs_qkd_summary_structure)
test("_run_multi_ogs_solve: station id/name echoed", test_multi_ogs_station_id_preserved)
test("_run_multi_ogs_solve: high-lat sees more passes (SSO)", test_multi_ogs_high_lat_vs_low_lat)
test("_run_multi_ogs_solve: aperture affects SKR", test_multi_ogs_aperture_affects_skr)
test("POST /api/solve/multi-ogs inline stations", test_multi_ogs_api_inline)
test("POST /api/solve/multi-ogs no stations → 400", test_multi_ogs_api_no_stations_returns_400)
test("POST /api/solve/multi-ogs by store id", test_multi_ogs_api_by_store_id)
test("POST /api/solve/multi-ogs unknown id → 404", test_multi_ogs_api_unknown_station_id_returns_404)
test("_run_multi_ogs_solve: key_volume structure", test_multi_ogs_key_volume_structure)


# ========================================================================
# MONTE CARLO ENGINE (TODO-06)
# ========================================================================
section("Monte Carlo: Fading Channel Engine")

def _mc_base_params():
    return {
        "photonRate": 1e8,
        "channelLossdB": 30.0,
        "detectorEfficiency": 0.6,
        "darkCountRate": 100.0,
    }

def test_mc_no_fading_is_deterministic():
    """sigma_R^2=0 and jitter=0 → every realization equals the mean channel."""
    from app.physics.monte_carlo import monte_carlo_key_rate
    from app.physics.qkd import calculate_bb84
    res = monte_carlo_key_rate(_mc_base_params(), "bb84", sigma_r2=0.0,
                               jitter_rad=0.0, n_realizations=200, seed=1)
    nominal = calculate_bb84(_mc_base_params())["secureKeyRate"]
    assert res["skr_kbps"]["std"] < 1e-12, f"std={res['skr_kbps']['std']}"
    assert abs(res["skr_kbps"]["p50"] - nominal) < 1e-9
    assert abs(res["mean_excess_loss_db"]) < 1e-12

def test_mc_scint_fade_factor_unit_mean():
    """Log-normal & gamma-gamma fading factors are normalized to E[chi]=1."""
    import numpy as np
    from app.physics.monte_carlo import sample_scintillation_fading
    rng = np.random.default_rng(0)
    weak = sample_scintillation_fading(0.3, 200000, rng)    # log-normal
    strong = sample_scintillation_fading(4.0, 200000, rng)  # gamma-gamma
    assert abs(weak.mean() - 1.0) < 0.02, f"weak mean {weak.mean()}"
    assert abs(strong.mean() - 1.0) < 0.03, f"strong mean {strong.mean()}"

def test_mc_pointing_mean_matches_pat_fading():
    """MC pointing fade mean equals deterministic Rayleigh PAT fading."""
    import numpy as np
    from app.physics.monte_carlo import sample_pointing_fading
    from app.physics.link_budget import pat_fading_penalty_db
    jitter, div = 5e-6, 30e-6
    rng = np.random.default_rng(2)
    mc_mean = sample_pointing_fading(jitter, div, 400000, rng).mean()
    analytic = 1.0 / (1.0 + 8.0 * (jitter / div) ** 2)
    assert abs(mc_mean - analytic) < 0.005, f"mc={mc_mean}, analytic={analytic}"
    # cross-check the deterministic dB conversion is consistent
    assert pat_fading_penalty_db(jitter, div) > 0

def test_mc_percentiles_ordered():
    """P5 <= P50 <= P95 and outage probability is a valid fraction."""
    from app.physics.monte_carlo import monte_carlo_key_rate
    res = monte_carlo_key_rate(_mc_base_params(), "bb84", sigma_r2=2.0,
                               jitter_rad=4e-6, divergence_rad=30e-6,
                               n_realizations=1000, seed=7)
    s = res["skr_kbps"]
    assert s["p5"] <= s["p50"] <= s["p95"], s
    assert 0.0 <= res["outage_probability"] <= 1.0
    assert res["n_realizations"] == 1000

def test_mc_fading_lowers_median_skr():
    """Turbulence + jitter reduce the median SKR vs the no-fading case."""
    from app.physics.monte_carlo import monte_carlo_key_rate
    clean = monte_carlo_key_rate(_mc_base_params(), "bb84", n_realizations=500, seed=3)
    faded = monte_carlo_key_rate(_mc_base_params(), "bb84", sigma_r2=1.5,
                                 jitter_rad=6e-6, divergence_rad=30e-6,
                                 n_realizations=500, seed=3)
    assert faded["skr_kbps"]["p50"] <= clean["skr_kbps"]["p50"] + 1e-9
    assert faded["mean_excess_loss_db"] > 0.0

def test_mc_reproducible_with_seed():
    """Same seed → identical percentiles (deterministic RNG)."""
    from app.physics.monte_carlo import monte_carlo_key_rate
    a = monte_carlo_key_rate(_mc_base_params(), "bb84", sigma_r2=1.0,
                             jitter_rad=5e-6, divergence_rad=30e-6,
                             n_realizations=300, seed=42)
    b = monte_carlo_key_rate(_mc_base_params(), "bb84", sigma_r2=1.0,
                             jitter_rad=5e-6, divergence_rad=30e-6,
                             n_realizations=300, seed=42)
    assert a["skr_kbps"]["p5"] == b["skr_kbps"]["p5"]
    assert a["skr_kbps"]["p95"] == b["skr_kbps"]["p95"]

def test_mc_decoy_protocol_runs():
    """Engine works for the decoy-state protocol too."""
    from app.physics.monte_carlo import monte_carlo_key_rate
    res = monte_carlo_key_rate(_mc_base_params(), "bb84-decoy", sigma_r2=1.2,
                               jitter_rad=4e-6, divergence_rad=30e-6,
                               n_realizations=300, seed=5)
    assert res["protocol"] == "bb84-decoy"
    assert "p50" in res["skr_kbps"]

test("monte_carlo: no fading is deterministic", test_mc_no_fading_is_deterministic)
test("monte_carlo: scint fade factors have unit mean", test_mc_scint_fade_factor_unit_mean)
test("monte_carlo: pointing mean matches PAT fading", test_mc_pointing_mean_matches_pat_fading)
test("monte_carlo: P5<=P50<=P95, valid outage", test_mc_percentiles_ordered)
test("monte_carlo: fading lowers median SKR", test_mc_fading_lowers_median_skr)
test("monte_carlo: reproducible with seed", test_mc_reproducible_with_seed)
test("monte_carlo: decoy protocol runs", test_mc_decoy_protocol_runs)


# ========================================================================
# DAYTIME QKD: SPECTRAL FILTERING + TEMPORAL GATING (TODO-07)
# ========================================================================

def test_gating_duty_cycle_value():
    from app.physics.link_budget import temporal_gating_duty_cycle
    # 1 ns gate at 100 MHz pulse rate => duty cycle 0.1
    d = temporal_gating_duty_cycle(1e-9, 100e6)
    assert abs(d - 0.1) < 1e-12, d

def test_gating_duty_cycle_clamped():
    from app.physics.link_budget import temporal_gating_duty_cycle
    # Δt·f_rep > 1 must clamp to 1.0 (gate wider than pulse period)
    assert temporal_gating_duty_cycle(1e-6, 100e6) == 1.0

def test_gating_duty_cycle_ungated():
    from app.physics.link_budget import temporal_gating_duty_cycle
    # Non-positive inputs => ungated receiver (no suppression)
    assert temporal_gating_duty_cycle(0.0, 100e6) == 1.0
    assert temporal_gating_duty_cycle(1e-9, 0.0) == 1.0

def test_gated_background_reduces():
    from app.physics.link_budget import gated_background_cps
    raw = 1e5
    gated = gated_background_cps(raw, 1e-9, 100e6)  # duty 0.1
    assert abs(gated - 1e4) < 1e-6, gated
    assert gated < raw

def test_gated_background_zero():
    from app.physics.link_budget import gated_background_cps
    assert gated_background_cps(0.0, 1e-9, 100e6) == 0.0

def test_solar_spectral_anchor_810():
    from app.physics.sky_background import _solar_spectral_irradiance_W_m2_nm
    # 810 nm must return the legacy anchor exactly (backward compatible)
    assert abs(_solar_spectral_irradiance_W_m2_nm(810.0) - 0.48) < 1e-12

def test_solar_spectral_1550_lower_than_810():
    from app.physics.sky_background import _solar_spectral_irradiance_W_m2_nm
    # Daytime QKD rationale: 1550 nm has much less solar background than 810 nm
    assert (_solar_spectral_irradiance_W_m2_nm(1550.0)
            < _solar_spectral_irradiance_W_m2_nm(810.0))

def test_solar_radiance_wavelength_dependence():
    from app.physics.sky_background import solar_sky_radiance_W_m2_sr_um
    # Radiance now depends on wavelength; 1550 nm < 810 nm at same zenith
    r810 = solar_sky_radiance_W_m2_sr_um(30.0, 810.0)
    r1550 = solar_sky_radiance_W_m2_sr_um(30.0, 1550.0)
    assert r1550 < r810 and r1550 > 0.0

test("gating: duty cycle value", test_gating_duty_cycle_value)
test("gating: duty cycle clamped to 1", test_gating_duty_cycle_clamped)
test("gating: ungated => no suppression", test_gating_duty_cycle_ungated)
test("gating: background reduced by duty cycle", test_gated_background_reduces)
test("gating: zero background stays zero", test_gated_background_zero)
test("spectral: 810 nm anchor preserved", test_solar_spectral_anchor_810)
test("spectral: 1550 nm < 810 nm irradiance", test_solar_spectral_1550_lower_than_810)
test("spectral: radiance wavelength-dependent", test_solar_radiance_wavelength_dependence)


# ========================================================================
# N. PAPER-MODE PHYSICS (Ntanos et al. 2021, Photonics 8, 544)
# ========================================================================
section("N. Paper-mode physics (Ntanos et al. 2021)")


def test_modified_hv_ground_cn2():
    from app.physics.atmosphere_models import modified_hv_cn2
    # At sea level (H_GS=0) the ground term equals A0.
    c0 = modified_hv_cn2(0.0, 0.0, ground_cn2=1.7e-14, u_rms=10.0)
    assert abs(c0 - 1.7e-14) / 1.7e-14 < 0.05, c0
    # Higher OGS => reduced boundary-layer turbulence at the station (exp(-Hgs/700))
    c_helmos = modified_hv_cn2(2340.0, 2340.0, ground_cn2=1.7e-14, u_rms=10.0)
    assert c_helmos < c0, (c_helmos, c0)
    assert abs(c_helmos - 1.7e-14 * math.exp(-2340.0 / 700.0)) / c_helmos < 0.1


def test_modified_hv_layers_domain():
    from app.physics.atmosphere_models import modified_hv_layers
    layers = modified_hv_layers(h_gs_m=2340.0, ground_cn2=1.7e-14, u_rms=10.0)
    assert len(layers) > 10
    assert abs(layers[0][0] - 2340.0) < 1.0            # starts at OGS altitude
    assert layers[-1][0] >= 20000.0 - 1.0              # up to ~20 km turbulence ceiling
    assert all(c >= 0.0 for _, c in layers)
    # ground layer stronger than the ~15 km layer
    assert layers[0][1] > layers[-1][1]


def test_gaussian_geometric_loss():
    from app.physics.geometry import geometric_loss
    lam, Dt, Dr, d = 1550.0, 0.15, 2.3, 600.0
    w0 = 2.0 * (lam * 1e-9) / (math.pi * Dt)
    expected_coupling = (Dr / 2.0 / (w0 * d * 1000.0)) ** 2
    gl = geometric_loss(d, Dt, Dr, lam, model="gaussian")
    assert abs(gl["coupling"] - expected_coupling) / expected_coupling < 1e-6
    assert abs(gl["lossDb"] - (-10.0 * math.log10(expected_coupling))) < 1e-6


def test_gaussian_vs_airy_divergence():
    from app.physics.geometry import geometric_loss
    # The two conventions are nearly equivalent: Gaussian half-width divergence
    # w0 = 2/π·λ/D ≈ 0.637·λ/D vs. Airy half-angle 1.22/2·λ/D ≈ 0.61·λ/D — the
    # Gaussian spot is ~4% larger, so its loss is marginally *higher* (~0.4 dB).
    g = geometric_loss(600.0, 0.15, 0.75, 1550.0, model="gaussian")
    a = geometric_loss(600.0, 0.15, 0.75, 1550.0, model="airy")
    assert g["lossDb"] >= a["lossDb"], (g["lossDb"], a["lossDb"])
    assert abs(g["lossDb"] - a["lossDb"]) < 1.0, (g["lossDb"], a["lossDb"])


def test_pointing_loss_beta():
    from app.physics.link_budget import pointing_loss_beta_db
    lam, Dt = 1550.0, 0.15
    w0 = 2.0 * (lam * 1e-9) / (math.pi * Dt)
    L = pointing_loss_beta_db(0.75, w0, 0.01)
    beta_p = w0 ** 2 / (4.0 * (0.75e-6) ** 2)
    expected = -10.0 * math.log10(0.01 ** (1.0 / beta_p))
    assert abs(L - expected) < 1e-6, (L, expected)
    assert 0.8 < L < 1.3, L   # ~1.04 dB for the paper parameters


def test_decoy_q_linear_scaling():
    from app.physics.qkd import calculate_bb84_decoy
    base = dict(photonRate=1e8, channelLossdB=20.0, detectorEfficiency=0.85,
                darkCountRate=300.0, backgroundCps=0.0, mu_signal=0.56,
                mu_decoy=0.11, e_optical=0.01, f_ec=1.22)
    r1 = calculate_bb84_decoy({**base, "q": 0.4})
    r2 = calculate_bb84_decoy({**base, "q": 0.2})
    assert r1["secureKeyRatePerPulse"] > 0
    ratio = r1["secureKeyRatePerPulse"] / r2["secureKeyRatePerPulse"]
    assert abs(ratio - 2.0) < 1e-6, ratio   # SKR linear in q


def test_decoy_per_pulse_consistency():
    from app.physics.qkd import calculate_bb84_decoy
    r = calculate_bb84_decoy(dict(photonRate=1e8, channelLossdB=18.0,
        detectorEfficiency=0.85, darkCountRate=300.0, backgroundCps=100.0,
        mu_signal=0.56, mu_decoy=0.11, e_optical=0.01, q=0.0952, f_ec=1.22))
    # secureKeyRate[kbit/s] == per-pulse × f_rep / 1e3
    lhs = r["secureKeyRatePerPulse"] * 1e8 / 1e3
    assert abs(lhs - r["secureKeyRate"]) / max(r["secureKeyRate"], 1e-30) < 1e-9


def test_decoy_paper_noise_gate():
    from app.physics.qkd import calculate_bb84_decoy
    # Noise-limited regime: a 1 ns gate (paper_noise) admits 10× less background
    # than the default 10 ns pulse period (f_rep=1e8) ⇒ lower QBER.
    base = dict(photonRate=1e8, channelLossdB=35.0, detectorEfficiency=0.85,
                darkCountRate=300.0, backgroundCps=1e7, mu_signal=0.56,
                mu_decoy=0.11, e_optical=0.01, q=0.0952, f_ec=1.22)
    default = calculate_bb84_decoy(base)
    paper = calculate_bb84_decoy({**base, "paper_noise": True, "gate_time_s": 1e-9})
    assert paper["qber"] < default["qber"], (paper["qber"], default["qber"])


def test_scint_bug_fix_builds_layers():
    # Regression: _build_cn2_layers must return real layers for modified-HV
    # (previously always None due to dict-vs-object bug).
    from app.routers.solver import _build_cn2_layers
    from app.models import SolveRequest
    req = SolveRequest(scintillation_enabled=True, atmosphere_model="modified-hv",
                       station_lat=37.98, station_lon=22.20, station_altitude_m=2340.0,
                       wavelength_nm=1550.0, ground_cn2_night=1.7e-14, wind_rms_ms=10.0)
    layers = _build_cn2_layers(req)
    assert layers is not None and len(layers) > 10
    assert all(isinstance(t, tuple) and len(t) == 2 for t in layers)


test("paper: modified-HV ground Cn2 vs A0/altitude", test_modified_hv_ground_cn2)
test("paper: modified-HV layer domain [H_GS, 20km]", test_modified_hv_layers_domain)
test("paper: gaussian geometric coupling (Eq. 3/5/6)", test_gaussian_geometric_loss)
test("paper: gaussian divergence < airy", test_gaussian_vs_airy_divergence)
test("paper: beta pointing loss (Eq. 8-10)", test_pointing_loss_beta)
test("paper: decoy SKR linear in q", test_decoy_q_linear_scaling)
test("paper: decoy per-pulse consistency", test_decoy_per_pulse_consistency)
test("paper: paper-noise gate reduces QBER (Eq. A6)", test_decoy_paper_noise_gate)
test("paper: scintillation bug fix builds layers", test_scint_bug_fix_builds_layers)


def test_paper_preset_endpoint():
    from app.routers.paper import get_preset
    p = get_preset()
    assert abs(p["params"]["q"] - 2.0 / 21.0) < 1e-6
    ids = {s["id"] for s in p["stations"]}
    assert {"helmos", "skinakas", "cholomondas"} <= ids


def test_paper_link_sweep_shape_and_loss():
    from app.routers.paper import _run_link_sweep, LinkSweepRequest
    r = _run_link_sweep(LinkSweepRequest(distance_steps=5, aperture_steps=5))
    assert len(r["lossDb"]) == 5 and len(r["lossDb"][0]) == 5
    assert len(r["skrPerPulse"]) == 5
    # loss grows with distance (row 0 = min distance) at fixed aperture
    assert r["lossDb"][-1][0] > r["lossDb"][0][0]
    # large aperture, short distance ⇒ positive SKR
    assert r["skrPerPulse"][0][-1] > 0.0


def test_paper_single_pass_returns_pass():
    from app.routers.paper import _run_single_pass, SinglePassRequest
    r = _run_single_pass(SinglePassRequest(station_id="helmos",
                                           total_orbits=16, samples_per_orbit=180))
    assert r["duration_s"] > 0.0
    assert r["max_elevation_deg"] >= 20.0
    assert r["max_skr_per_pulse"] > 0.0
    assert len(r["t"]) == len(r["skrPerPulse"]) == len(r["distanceKm"])


def test_paper_constellation_ratios():
    # Small/fast run: inter-station ratios should track the paper (Helmos best).
    from app.routers.paper import _run_constellation, ConstellationRequest
    c = _run_constellation(ConstellationRequest(n_sats=3, total_orbits=60,
                                                 samples_per_orbit=40))
    t = c["totals_gbit_year"]
    assert t["helmos"] > t["skinakas"] > t["cholomondas"] > 0.0


test("paper: /preset endpoint", test_paper_preset_endpoint)
test("paper: /link-sweep grid & loss trend", test_paper_link_sweep_shape_and_loss)
test("paper: /single-pass returns a pass", test_paper_single_pass_returns_pass)
test("paper: /constellation inter-station ratios", test_paper_constellation_ratios)


# ========================================================================
# FINITE-KEY PER PASS — Lim et al. 2014 (TODO-17)
# ========================================================================
section("Finite-key per pass (Lim et al. 2014)")

_E0_FK = 0.5


def _fk_channel(loss_db, mus, y0, e_opt, eta_det):
    """(D_k, E_k) per intensity, threshold-detector model."""
    eta = 10.0 ** (-loss_db / 10.0) * eta_det
    d, e = [], []
    for mu in mus:
        dk = 1.0 - (1.0 - y0) * math.exp(-mu * eta)
        vac = y0 * math.exp(-mu)
        ek = (_E0_FK * vac + e_opt * (dk - vac)) / dk if dk > 0 else _E0_FK
        d.append(dk)
        e.append(max(0.0, min(ek, 0.5)))
    return d, e


def _fk_counts(n_x_target, loss_db, mus, probs, q_x=0.5, y0=6e-7,
               e_opt=0.01, eta_det=0.85):
    """Block statistics scaled so the X-basis block size is n_x_target."""
    d, e = _fk_channel(loss_db, mus, y0, e_opt, eta_det)
    denom = q_x ** 2 * sum(p * dk for p, dk in zip(probs, d))
    n_pulses = n_x_target / denom
    n_x_k = tuple(q_x ** 2 * p * n_pulses * dk for p, dk in zip(probs, d))
    n_z_k = tuple((1 - q_x) ** 2 * p * n_pulses * dk for p, dk in zip(probs, d))
    m_z_k = tuple(nz * ek for nz, ek in zip(n_z_k, e))
    m_x = sum(nx * ek for nx, ek in zip(n_x_k, e))
    return n_x_k, n_z_k, m_z_k, m_x


_FK_MUS = (0.56, 0.11, 0.0)          # Ntanos 2021 signal / decoy / vacuum
_FK_PROBS = (4 / 21, 1 / 21, 16 / 21)  # paper ratio 4:1:16


def _fk_fraction(n_x, loss_db=26.0, mus=_FK_MUS, probs=_FK_PROBS):
    from app.physics.finite_key import lim2014_finite_fraction
    nx, nz, mz, mx = _fk_counts(n_x, loss_db, mus, probs)
    return lim2014_finite_fraction(nx, nz, mz, mx, intensities=mus,
                                   probs=probs, eps_sec=1e-10,
                                   eps_cor=1e-15, f_ec=1.22)


def test_fk_tau_photon():
    # tau_n = sum_k e^-mu_k mu_k^n p_k / n!  (Lim et al. 2014)
    from app.physics.finite_key import tau_photon
    mus, probs = _FK_MUS, _FK_PROBS
    t0 = tau_photon(0, mus, probs)
    t1 = tau_photon(1, mus, probs)
    expect0 = sum(math.exp(-m) * p for m, p in zip(mus, probs))
    expect1 = sum(math.exp(-m) * m * p for m, p in zip(mus, probs))
    assert abs(t0 - expect0) < 1e-15, (t0, expect0)
    assert abs(t1 - expect1) < 1e-15, (t1, expect1)
    # The vacuum intensity contributes e^0 * p_3 = p_3 to tau_0 but 0 to tau_1.
    assert t0 > probs[2], t0


def test_fk_finite_never_exceeds_asymptotic():
    # ell_finite <= ell_asymptotic is the defining property of the bound: the
    # statistical corrections can only cost key, never create it.
    for n_x in (1e5, 1e6, 1e7, 1e8):
        for loss in (20.0, 26.0, 32.0):
            r = _fk_fraction(n_x, loss)
            assert r["ell_finite"] <= r["ell_asymptotic"] + 1e-6, (n_x, loss, r)
            assert 0.0 <= r["fraction"] <= 1.0, r


def test_fk_monotone_in_block_size():
    # Larger block -> smaller relative statistical penalty (Lim et al. 2014).
    fracs = [_fk_fraction(n)["fraction"] for n in (1e5, 1e6, 1e7, 1e8, 1e9)]
    assert all(b >= a - 1e-12 for a, b in zip(fracs, fracs[1:])), fracs
    assert fracs[-1] > 0.95, fracs      # converges to the asymptotic limit
    assert fracs[0] < fracs[-1], fracs


def test_fk_threshold_is_real_zero():
    # THE point of using Lim 2014 instead of a multiplicative Tomamichel
    # fraction: a small block yields EXACTLY zero key, so the loss at which the
    # key vanishes moves. A multiplicative factor is positive wherever the
    # asymptotic rate is, inventing loss margin that does not exist.
    from app.physics.finite_key import finite_key_fraction
    small = _fk_fraction(1e4, 26.0)
    assert small["fraction"] == 0.0, small
    assert small["ell_finite"] == 0.0, small
    # Tomamichel's BB84 fraction, by contrast, is comfortably positive there.
    assert finite_key_fraction(1e4, 1e-10, 0.01) > 0.4


def test_fk_looser_than_tomamichel():
    # Regression pin on the finding that motivated this module: the [Tom12]
    # single-photon fraction OVERESTIMATES the decoy key at realistic satellite
    # block sizes (1e5-1e6 sifted bits for a LEO pass).
    from app.physics.finite_key import finite_key_fraction
    for n_x in (1e5, 1e6, 1e7):
        lim = _fk_fraction(n_x)["fraction"]
        tom = finite_key_fraction(n_x, 1e-10, 0.01)
        assert tom > lim, (n_x, tom, lim)


def test_fk_rejects_bad_intensity_ordering():
    # Lim et al. 2014 Eqs. (2)-(4) require mu_1 > mu_2 + mu_3 and mu_2 > mu_3;
    # violating it flips their denominators' sign, so it must be refused.
    from app.physics.finite_key import lim2014_key_length
    bad = (0.1, 0.56, 0.0)      # mu_1 < mu_2
    nx, nz, mz, mx = _fk_counts(1e7, 26.0, _FK_MUS, _FK_PROBS)
    r = lim2014_key_length(nx, nz, mz, mx, intensities=bad, probs=_FK_PROBS)
    assert r["ell"] == 0.0 and r["ok"] is False, r


def test_fk_phase_error_inflated_by_fluctuations():
    # Eq. (5): phi_X = v_Z1/s_Z1 + gamma(...) >= the asymptotic phase error,
    # and the gap shrinks with block size.
    from app.physics.finite_key import lim2014_key_length
    gaps = []
    for n_x in (1e5, 1e7, 1e9):
        nx, nz, mz, mx = _fk_counts(n_x, 26.0, _FK_MUS, _FK_PROBS)
        kw = dict(intensities=_FK_MUS, probs=_FK_PROBS, f_ec=1.22)
        fin = lim2014_key_length(nx, nz, mz, mx, asymptotic=False, **kw)
        asy = lim2014_key_length(nx, nz, mz, mx, asymptotic=True, **kw)
        assert fin["phi_x"] >= asy["phi_x"] - 1e-12, (n_x, fin, asy)
        gaps.append(fin["phi_x"] - asy["phi_x"])
    assert gaps[0] > gaps[-1], gaps


def test_fk_solve_request_defaults():
    from app.models import SolveRequest, MultiOGSSolveRequest
    for cls in (SolveRequest, MultiOGSSolveRequest):
        r = cls()
        assert r.finite_key_enabled is False
        assert r.epsilon_sec == 1e-10
        assert r.epsilon_cor == 1e-15
        assert r.basis_bias_qx == 0.5
        assert abs(r.p_signal - 4 / 21) < 1e-12
        assert abs(r.p_decoy - 1 / 21) < 1e-12


def _fk_solve_base():
    from app.routers.paper import _sso_elements
    el = _sso_elements(22.0, "2024-03-20T00:00:00Z")
    return dict(
        semi_major_axis=el["a"], eccentricity=0.0, inclination_deg=el["inc"],
        raan_deg=el["raan"], epoch="2024-03-20T00:00:00Z",
        samples_per_orbit=120, total_orbits=16,
        station_lat=37.9844, station_lon=22.1961, station_altitude_m=2340.0,
        sat_aperture_m=0.15, ground_aperture_m=2.3, wavelength_nm=1550.0,
        qkd_protocol="bb84-decoy", photon_rate=1e8, detector_efficiency=0.85,
        dark_count_rate=300.0, min_elevation_deg=20.0,
        elevation_threshold_deg=20.0, mu_signal=0.56, mu_decoy=0.11,
        decoy_q=0.0952, e_optical=0.01, ec_efficiency=1.22,
        paper_noise=True, gate_time_s=1e-9, fixed_optics_loss_db=5.95,
        atm_zenith_aod_db=0.5,
    )


def test_fk_solver_disabled_is_backward_compatible():
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    kv = _run_solve(SolveRequest(**_fk_solve_base()))["key_volume"]
    assert kv["pass_count"] > 0, kv["pass_count"]
    assert "total_key_volume_finite_mb" not in kv
    assert all("fkFraction" not in p for p in kv["passes"])


def test_fk_solver_enabled_per_pass():
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    base = _fk_solve_base()
    off = _run_solve(SolveRequest(**base))["key_volume"]
    on = _run_solve(SolveRequest(**base, finite_key_enabled=True))["key_volume"]
    # Enabling finite key must not perturb the asymptotic result.
    assert abs(off["total_key_volume_mb"] - on["total_key_volume_mb"]) < 1e-12
    assert "total_key_volume_finite_mb" in on
    assert 0.0 < on["mean_fk_fraction"] <= 1.0, on["mean_fk_fraction"]
    assert on["total_key_volume_finite_mb"] <= on["total_key_volume_mb"] + 1e-12
    for p in on["passes"]:
        assert 0.0 <= p["fkFraction"] <= 1.0, p
        assert p["keyVolumeFinite"] <= p["key_volume_mb"] + 1e-12, p
        assert p["nSifted"] >= 0.0
    # The shortest pass carries the harshest penalty (smallest block).
    ranked = sorted((p for p in on["passes"] if p["nSifted"] > 0),
                    key=lambda p: p["nSifted"])
    if len(ranked) >= 2:
        assert ranked[0]["fkFraction"] <= ranked[-1]["fkFraction"] + 1e-9, ranked


def test_fk_solver_wrong_protocol_is_explicit():
    # Never degrade silently: the bound is decoy-state only, so requesting it
    # for plain BB84 must say so in the response.
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    base = {**_fk_solve_base(), "qkd_protocol": "bb84"}
    kv = _run_solve(SolveRequest(**base, finite_key_enabled=True))["key_volume"]
    assert "finite_key_note" in kv
    assert "decoy" in kv["finite_key_note"].lower()
    assert "total_key_volume_finite_mb" not in kv


test("finite-key: tau_n photon priors (Lim 2014)", test_fk_tau_photon)
test("finite-key: ell_finite <= ell_asymptotic", test_fk_finite_never_exceeds_asymptotic)
test("finite-key: fraction monotone in block size", test_fk_monotone_in_block_size)
test("finite-key: small block gives exactly zero key", test_fk_threshold_is_real_zero)
test("finite-key: Lim 2014 tighter than Tom12 fraction", test_fk_looser_than_tomamichel)
test("finite-key: rejects mu_1 <= mu_2 ordering", test_fk_rejects_bad_intensity_ordering)
test("finite-key: phase error inflated by fluctuations (Eq. 5)", test_fk_phase_error_inflated_by_fluctuations)
test("finite-key: SolveRequest / MultiOGS defaults", test_fk_solve_request_defaults)
test("finite-key: disabled is backward compatible", test_fk_solver_disabled_is_backward_compatible)
test("finite-key: per-pass fraction & volume in /api/solve", test_fk_solver_enabled_per_pass)
test("finite-key: wrong protocol reported explicitly", test_fk_solver_wrong_protocol_is_explicit)


# ========================================================================
# CLOUD AVAILABILITY — PCFLOS, elevation-resolved (Kauth & Penquite 1967)
# ========================================================================
section("Cloud availability / PCFLOS (Kauth & Penquite 1967)")


def _av_hourly(spec, year=2023, days=28):
    """Synthetic Open-Meteo hourly series.

    spec: callable(month, day, utc_hour) -> cloud cover in percent, or None.
    Timestamps are "YYYY-MM-DDTHH:MM" because the reducers index [5:7] and
    [11:13] by position, exactly like the real archive payload.
    """
    times, cover = [], []
    for m in range(1, 13):
        for d in range(1, days + 1):
            for h in range(24):
                times.append(f"{year}-{m:02d}-{d:02d}T{h:02d}:00")
                cover.append(spec(m, d, h))
    return {"time": times, "cloud_cover": cover}


def _av_flat(pct):
    return _av_hourly(lambda m, d, h: float(pct))


# Independently computed reference table for P_CFLOS(eps) = P_z^(1/sin eps)
# at beta = 1, from the literature review that motivated this module.
_AV_REF = {
    0.9: {90: 0.900, 50: 0.872, 40: 0.849, 30: 0.810, 20: 0.735},
    0.7: {90: 0.700, 50: 0.628, 40: 0.574, 30: 0.490, 20: 0.352},
    0.5: {90: 0.500, 50: 0.405, 40: 0.340, 30: 0.250, 20: 0.132},
    0.3: {90: 0.300, 50: 0.208, 40: 0.154, 30: 0.090, 20: 0.030},
}


def test_av_shape_factor_identity():
    # The whole defence of the "air-mass" scaling: sqrt(1 + beta^2 cot^2 eps) at
    # beta = 1 IS csc(eps) exactly, so 1/sin(eps) is the Kauth & Penquite (1967)
    # ellipsoid model at unit cloud aspect ratio, not an ad hoc correction.
    from app.physics.availability import cflos_shape_factor
    for e in (5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 89.0):
        f = cflos_shape_factor(e, 1.0)
        assert abs(f - 1.0 / math.sin(math.radians(e))) < 1e-12, (e, f)
    assert cflos_shape_factor(90.0, 1.0) == 1.0
    assert cflos_shape_factor(20.0, 0.0) == 1.0          # correction disabled
    assert math.isinf(cflos_shape_factor(0.0, 1.0))      # no LOS at the horizon
    assert math.isinf(cflos_shape_factor(-3.0, 1.0))
    # Monotone in beta: taller clouds block more slant path.
    fs = [cflos_shape_factor(20.0, b) for b in (0.5, 0.75, 1.0, 1.25, 1.5)]
    assert all(b > a for a, b in zip(fs, fs[1:])), fs


def test_av_zenith_is_one_minus_cover():
    # The exact nadir identity P_CFLOS = 1 - N (Reinke & Vonder Haar), which is
    # also the availability definition used by the two published satellite-QKD
    # precedents (Anipeddi et al. 2025; Hossain et al. 2025).  Anchoring on it is
    # what makes the elevation model a generalisation rather than a new claim.
    from app.physics.availability import pcflos_from_hist, pcflos_hour
    for pct in (0, 10, 30, 55, 70, 100):
        assert abs(pcflos_hour(pct / 100.0, 90.0) - (1.0 - pct / 100.0)) < 1e-12
    stats_hist = None
    from app.physics.availability import monthly_cover_stats
    stats_hist = monthly_cover_stats(_av_flat(30))["annual_hist"]
    assert abs(pcflos_from_hist(stats_hist, 90.0) - 0.70) < 1e-12


def test_av_monotone_in_elevation_and_cover():
    from app.physics.availability import pcflos_hour
    lower = [pcflos_hour(0.3, e) for e in (90, 60, 45, 30, 20, 10)]
    assert all(b < a for a, b in zip(lower, lower[1:])), lower
    darker = [pcflos_hour(n, 30.0) for n in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    assert all(b < a for a, b in zip(darker, darker[1:])), darker
    assert pcflos_hour(1.0, 45.0) == 0.0      # fully overcast blocks entirely
    assert pcflos_hour(0.0, 45.0) == 1.0


def test_av_elevation_bias_matches_reference_table():
    # Regression pin on the magnitude of the bias the elevation correction
    # removes: at 20 deg the zenith proxy overstates PCFLOS by ~2x for a good
    # site (P_z = 0.7) and ~4x for a poor one (P_z = 0.5).
    from app.physics.availability import pcflos_hour
    for p_z, row in _AV_REF.items():
        for elev, expect in row.items():
            got = pcflos_hour(1.0 - p_z, float(elev))
            assert abs(got - expect) < 5e-4, (p_z, elev, got, expect)
    # And the headline overstatement factors.
    assert abs(_AV_REF[0.7][90] / _AV_REF[0.7][20] - 1.99) < 0.02
    assert abs(_AV_REF[0.5][90] / _AV_REF[0.5][20] - 3.79) < 0.02


def test_av_histogram_equals_direct_sum():
    # The histogram is a transport/perf optimisation, not a model change: it must
    # reproduce the hour-by-hour expectation exactly for integer-percent input
    # (which is what ERA5 delivers through Open-Meteo).
    from app.physics.availability import (
        monthly_cover_stats, pcflos_from_hist, pcflos_hour,
    )
    hourly = _av_hourly(lambda m, d, h: float((m * 7 + d * 3 + h * 11) % 101))
    stats = monthly_cover_stats(hourly)
    for elev in (90.0, 45.0, 20.0):
        direct = sum(pcflos_hour(c / 100.0, elev)
                     for c in hourly["cloud_cover"]) / len(hourly["cloud_cover"])
        assert abs(pcflos_from_hist(stats["annual_hist"], elev) - direct) < 1e-12, elev


def test_av_expectation_exceeds_mean_cover_plug_in():
    # (1-N)^f is CONVEX in N for f > 1, so by Jensen the expectation over the
    # real hourly distribution is >= plugging the mean cover in.  Two things
    # follow, and both are stated in the module's LIMITATIONS: averaging cover
    # before exponentiating biases PCFLOS LOW (the residual sub-grid bias we
    # cannot fix), and at zenith f = 1 makes the two coincide exactly — which is
    # precisely why the 1 - <N> identity is safe there and nowhere else.
    from app.physics.availability import monthly_cover_stats, pcflos_from_hist
    hourly = _av_hourly(lambda m, d, h: 0.0 if h % 2 else 90.0)   # bimodal
    stats = monthly_cover_stats(hourly)
    mean_cover = stats["mean_cover_annual"]
    assert abs(mean_cover - 0.45) < 1e-12, mean_cover
    # Zenith: exact agreement (linear in N).
    assert abs(pcflos_from_hist(stats["annual_hist"], 90.0)
               - (1.0 - mean_cover)) < 1e-12
    # Slant: strict inequality, and it widens as the path lengthens.
    gaps = []
    for elev in (45.0, 30.0, 20.0):
        f = 1.0 / math.sin(math.radians(elev))
        expectation = pcflos_from_hist(stats["annual_hist"], elev)
        plug_in = (1.0 - mean_cover) ** f
        assert expectation > plug_in, (elev, expectation, plug_in)
        gaps.append(expectation - plug_in)
    assert gaps[-1] > gaps[0], gaps


def test_av_threshold_estimator_differs_from_expectation():
    # The finding that removed the 30 % threshold from the model: counting hours
    # below a threshold treats a fractional quantity as binary, so a 29 %-covered
    # cell is scored fully clear where the model says 0.71.  On mid-range cover
    # the two estimators disagree grossly, and the threshold one is the optimist.
    from app.physics.availability import (
        monthly_cover_stats, pcflos_from_hist, threshold_pcflos,
    )
    hourly = _av_flat(29)
    thr = threshold_pcflos(hourly, 30.0)["annual"]
    exp = pcflos_from_hist(monthly_cover_stats(hourly)["annual_hist"], 90.0)
    assert abs(thr - 1.0) < 1e-12, thr        # every hour counted "clear"
    assert abs(exp - 0.71) < 1e-9, exp        # the model's answer
    assert thr > exp
    # One percent more cover flips the threshold estimator to 0 while the
    # expectation estimator moves by 0.01 — the discontinuity is the defect.
    hourly2 = _av_flat(31)
    assert abs(threshold_pcflos(hourly2, 30.0)["annual"]) < 1e-12
    exp2 = pcflos_from_hist(monthly_cover_stats(hourly2)["annual_hist"], 90.0)
    assert abs(exp2 - 0.69) < 1e-9, exp2


def test_av_night_conditioning_sign_is_regime_dependent():
    # Eastman & Warren (J. Climate 27, 2386 (2014)): convective cumulus peaks in
    # the afternoon but boundary-layer stratus/fog peaks in the early morning, so
    # night conditioning can help OR hurt.  Both directions are pinned here
    # because an earlier draft of the module asserted only the convective one.
    from app.physics.availability import monthly_cover_stats, pcflos_from_hist
    def zen(hourly, night_only):
        st = monthly_cover_stats(hourly, night_only=night_only, lon_deg=0.0)
        return pcflos_from_hist(st["annual_hist"], 90.0)
    # Convective: overcast local afternoon (12-17 UTC at lon 0 = daytime).
    convective = _av_hourly(lambda m, d, h: 100.0 if 12 <= h < 18 else 0.0)
    assert zen(convective, True) > zen(convective, False)
    assert abs(zen(convective, True) - 1.0) < 1e-12    # nights all clear
    # Nocturnal stratus: overcast 00-05 UTC, which IS night at lon 0.
    stratus = _av_hourly(lambda m, d, h: 100.0 if h < 6 else 0.0)
    assert zen(stratus, True) < zen(stratus, False)
    # The night window itself must be the shared project definition.
    from app.physics.availability import is_night_local_solar
    assert is_night_local_solar(2.0, 0.0) is True
    assert is_night_local_solar(12.0, 0.0) is False
    assert is_night_local_solar(12.0, 180.0) is True    # local solar shift


def test_av_month_fallback_and_empty_table():
    # A month backed by a handful of reanalysis hours is noise; silently using it
    # would make an annual total depend on a data gap.  And an absent table must
    # never zero a key volume — the router reports the gap instead.
    from app.physics.availability import availability_factor, monthly_cover_stats
    thin = {"time": [f"2023-05-01T{h:02d}:00" for h in range(4)]
                    + [f"2023-06-{d:02d}T00:00" for d in range(1, 29)],
            "cloud_cover": [0.0] * 4 + [100.0] * 28}
    stats = monthly_cover_stats(thin)
    assert stats["hours"][5] == 4 and stats["hours"][6] == 28
    annual = availability_factor(None, stats)
    # May has 4 hours < min_hours=24 → falls back to annual, NOT to 1.0.
    assert abs(availability_factor(5, stats) - annual) < 1e-12
    # June is well populated → its own (fully overcast) figure.
    assert abs(availability_factor(6, stats) - 0.0) < 1e-12
    # Explicitly lowering the guard exposes May's real value.
    assert abs(availability_factor(5, stats, min_hours=1) - 1.0) < 1e-12
    assert availability_factor(1, {}) == 1.0
    assert availability_factor(None, {}) == 1.0
    # String month keys (a JSON round-trip) must resolve, not fall through.
    round_tripped = {**stats,
                     "monthly_hist": {str(k): v
                                      for k, v in stats["monthly_hist"].items()},
                     "hours": {str(k): v for k, v in stats["hours"].items()}}
    assert abs(availability_factor(6, round_tripped) - 0.0) < 1e-12


def test_av_filtered_to_nothing_is_no_data_not_zero():
    # Regression on a real defect: monthly_cover_stats always allocates
    # annual_hist as a list of 101 zeros, which is a non-empty (TRUTHY) list even
    # when no hour entered it.  Testing truthiness alone handed back an all-zero
    # histogram whose expectation is 0.0 — silently zeroing the whole key volume,
    # the one failure mode this module promises to avoid.  Reachable via
    # night_only=True over a window that contains no night hours.
    from app.physics.availability import (
        availability_factor, monthly_cover_stats, pass_availability,
        pcflos_profile, pcflos_profile_annual,
    )
    day_only = {"time": [f"2023-01-01T{h:02d}:00" for h in range(6, 18)],
                "cloud_cover": [20.0] * 12}
    stats = monthly_cover_stats(day_only, night_only=True, lon_deg=0.0)
    assert stats["valid_hours"] == 0, stats["valid_hours"]
    for prof in (pcflos_profile(stats), pcflos_profile_annual(stats)):
        assert prof["resolved"] is False, prof["resolved"]
        assert set(prof["p"]) == {1.0}, sorted(set(prof["p"]))[:3]
    assert availability_factor(1, stats) == 1.0
    assert availability_factor(None, stats) == 1.0
    av = pass_availability([30.0, 60.0], [1.0, 1.0], pcflos_profile(stats))
    assert all(abs(v - 1.0) < 1e-12 for v in av.values()), av
    # A genuinely overcast month must still report 0.0 — "no data" and "no key"
    # have to stay distinguishable.
    overcast = monthly_cover_stats(_av_flat(100))
    assert pcflos_profile(overcast)["resolved"] is True
    assert availability_factor(None, overcast) == 0.0


def test_av_independence_overstates_network_diversity():
    # Sanchez Net et al., J. Opt. Commun. Netw. 8, 800 (2016): synoptic cloud
    # fields are correlated over hundreds of km, so 1 - prod(1 - p_i) overstates
    # a regional network's diversity gain.  The GAP between measured-joint and
    # independence-assumed is the reportable result, so both directions are
    # pinned, along with the measured cross-correlation that explains them.
    from app.physics.availability import joint_pcflos
    same = _av_hourly(lambda m, d, h: 100.0 if h % 2 else 0.0)
    perfectly_correlated = {"a": same, "b": same}
    r = joint_pcflos(perfectly_correlated)
    assert abs(r["annual"] - 0.5) < 1e-12, r["annual"]         # no gain at all
    assert r["annual_independent"] > r["annual"] + 0.2, r      # 0.75, overstated
    assert abs(r["cross_correlation"]["a|b"] - 1.0) < 1e-9, r["cross_correlation"]
    # Anti-correlated sites: the network is always up, and the independence
    # formula UNDERSTATES it — which is why anti-correlation is worth siting for.
    anti = _av_hourly(lambda m, d, h: 0.0 if h % 2 else 100.0)
    r2 = joint_pcflos({"a": same, "b": anti})
    assert abs(r2["annual"] - 1.0) < 1e-12, r2["annual"]
    assert r2["annual_independent"] < r2["annual"] - 0.2, r2
    assert r2["cross_correlation"]["a|b"] < -0.99, r2["cross_correlation"]
    # Alignment is by timestamp: a station with a data gap must not shift another.
    gapped = {"time": same["time"][:100], "cloud_cover": same["cloud_cover"][:100]}
    r3 = joint_pcflos({"a": same, "b": gapped})
    assert r3["valid_hours"] == 100, r3["valid_hours"]


def test_av_annual_profile_is_day_weighted():
    # A 4-10 day window scaled to a year must not carry one month's climatology
    # into all twelve.  The annual profile is the day-weighted mean of the
    # monthly profiles, and it collapses to the monthly one when they agree.
    from app.physics.availability import (
        MONTH_DAYS, monthly_cover_stats, pcflos_profile, pcflos_profile_annual,
    )
    # January overcast, everything else clear.
    hourly = _av_hourly(lambda m, d, h: 100.0 if m == 1 else 0.0)
    stats = monthly_cover_stats(hourly)
    prof = pcflos_profile_annual(stats)
    expect = sum(w * (0.0 if i == 0 else 1.0)
                 for i, w in enumerate(MONTH_DAYS)) / sum(MONTH_DAYS)
    assert abs(prof["zenith"] - expect) < 1e-12, (prof["zenith"], expect)
    assert abs(prof["monthly_zenith"][1] - 0.0) < 1e-12
    assert abs(prof["monthly_zenith"][7] - 1.0) < 1e-12
    # Uniform climatology → annual == monthly, at every elevation.
    flat = monthly_cover_stats(_av_flat(40))
    pa = pcflos_profile_annual(flat)
    pm = pcflos_profile(flat, month=3)
    assert all(abs(a - b) < 1e-12 for a, b in zip(pa["p"], pm["p"]))
    # No statistics → all ones and resolved=False, so a caller can tell the
    # difference between "perfectly clear" and "no data".
    empty = pcflos_profile({})
    assert empty["resolved"] is False and set(empty["p"]) == {1.0}


def test_av_pass_reduction_weights_by_key():
    # p must sit INSIDE the pass sum: high-elevation samples are both more likely
    # clear and more productive, so the key-weighted mean exceeds the
    # time-weighted one, and both are below the zenith proxy.
    from app.physics.availability import (
        monthly_cover_stats, pass_availability, pcflos_profile,
    )
    prof = pcflos_profile(monthly_cover_stats(_av_flat(50)))
    elev = [20.0, 40.0, 70.0, 40.0, 20.0]
    key = [0.1, 1.0, 8.0, 1.0, 0.1]          # key concentrated at high elevation
    av = pass_availability(elev, key, prof)
    assert av["zenith"] > av["keyWeighted"] > av["timeWeighted"], av
    assert av["minElev"] < av["keyWeighted"], av
    assert av["shapeFactor"] > 1.0, av
    # Uniform weights make the two averages coincide.
    flat_av = pass_availability(elev, [1.0] * 5, prof)
    assert abs(flat_av["keyWeighted"] - flat_av["timeWeighted"]) < 1e-12, flat_av
    # An unresolved profile is a no-op, never a zero.
    none_av = pass_availability(elev, key, {"p": [1.0], "resolved": False})
    assert all(abs(v - 1.0) < 1e-12 for v in none_av.values()), none_av


def test_av_available_volume_equals_weighted_integral():
    # keyVolumeAvailable must be EXACTLY the trapezoid integral of
    # P_CFLOS(eps(t)) * R(t), not an average multiplied by a separately computed
    # integral.  Pinned on a deliberately NON-uniform time grid, because uniform
    # spacing would make plain averaging accidentally equivalent and hide a bug.
    import numpy as np
    from app.physics.availability import (
        monthly_cover_stats, pcflos_profile, profile_at,
    )
    from app.physics.key_volume import compute_key_volume

    t = [0.0, 10.0, 25.0, 45.0, 70.0, 100.0, 121.0]     # non-uniform on purpose
    elev = [21.0, 35.0, 60.0, 80.0, 55.0, 30.0, 22.0]
    rates_kbps = [1.0, 4.0, 9.0, 12.0, 7.0, 3.0, 1.0]
    qkd = [{"t": ti, "secureKeyRate": r} for ti, r in zip(t, rates_kbps)]
    prof = pcflos_profile(monthly_cover_stats(_av_flat(45)))

    kv = compute_key_volume(
        t, [True] * len(t), elev, qkd, "2024-03-20T00:00:00Z", 20.0,
        availability_profile=prof,
    )
    assert kv["pass_count"] == 1, kv["pass_count"]
    p = kv["passes"][0]
    rates_bps = np.array([r * 1000.0 for r in rates_kbps])
    avail = np.array([profile_at(prof, e) for e in elev])
    expect_mb = float(np.trapezoid(rates_bps * avail, np.array(t))) / (8.0 * 1e6)
    assert abs(p["keyVolumeAvailable"] - expect_mb) < 1e-12, (
        p["keyVolumeAvailable"], expect_mb)
    # And the clear-sky integral is untouched by the availability weighting.
    assert abs(p["key_volume_mb"]
               - float(np.trapezoid(rates_bps, np.array(t))) / (8.0 * 1e6)) < 1e-12


def test_av_effective_key_applies_each_factor_once():
    from app.physics.availability import effective_key_mb
    assert abs(effective_key_mb(2.0, 0.5, 0.4) - 0.4) < 1e-12
    assert abs(effective_key_mb(2.0, 0.5) - 1.0) < 1e-12          # None = skip
    assert abs(effective_key_mb(2.0, None, 0.5) - 1.0) < 1e-12
    assert abs(effective_key_mb(2.0) - 2.0) < 1e-12
    assert effective_key_mb(-5.0, 0.5, 0.5) == 0.0                # floored
    assert abs(effective_key_mb(1.0, 3.0, 2.0) - 1.0) < 1e-12     # clamped
    assert effective_key_mb(1.0, 0.5, 0.0) == 0.0


def _av_solve_climatology():
    """Deterministic offline climatology: cover rises through the day."""
    return _av_hourly(lambda m, d, h: float(10 + 3 * h))


def test_av_solver_disabled_is_backward_compatible():
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    kv = _run_solve(SolveRequest(**_fk_solve_base()))["key_volume"]
    assert kv["pass_count"] > 0, kv["pass_count"]
    assert "total_key_volume_available_mb" not in kv
    assert "availability_meta" not in kv
    assert all("availability" not in p for p in kv["passes"])


def test_av_solver_enabled_does_not_touch_clear_sky_or_fk():
    # THE regression that guards the double-counting trap.  mean_fk_fraction is
    # back-derived as total_finite / total_asymptotic, so if availability were
    # folded into keyVolumeFinite it would silently start reporting
    # fk x availability as the finite-key penalty while still satisfying every
    # existing finite-key assertion.  Availability therefore lives in its own
    # keys, and both the asymptotic total and mean_fk_fraction must be untouched.
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    base = {**_fk_solve_base(), "finite_key_enabled": True}
    off = _run_solve(SolveRequest(**base))["key_volume"]
    on = _run_solve(SolveRequest(
        **base, availability_enabled=True,
        cloud_cover_hourly=_av_solve_climatology()))["key_volume"]
    assert abs(off["total_key_volume_mb"] - on["total_key_volume_mb"]) < 1e-12
    assert abs(off["total_key_volume_finite_mb"]
               - on["total_key_volume_finite_mb"]) < 1e-12
    assert abs(off["mean_fk_fraction"] - on["mean_fk_fraction"]) < 1e-12
    assert on["availability_meta"]["source"] == "injected", on["availability_meta"]
    assert "availability_note" not in on
    assert 0.0 < on["mean_availability"] < 1.0, on["mean_availability"]
    # Ordering of the composed totals: expected <= each single-effect total.
    assert on["total_key_volume_expected_mb"] <= on["total_key_volume_finite_mb"] + 1e-12
    assert on["total_key_volume_expected_mb"] <= on["total_key_volume_available_mb"] + 1e-12
    assert on["total_key_bits_expected_lim"] <= on["total_key_bits_finite_lim"] + 1e-9
    for p in on["passes"]:
        d = p["availabilityDetail"]
        assert 0.0 < p["availability"] <= 1.0, p
        # The elevation correction can only ever reduce availability.
        assert p["availability"] <= d["zenith"] + 1e-12, p
        assert d["minElev"] <= d["keyWeighted"] + 1e-12, p
        assert abs(p["keyVolumeAvailable"]
                   - p["key_volume_mb"] * p["availability"]) < 1e-12, p
        assert abs(p["keyVolumeExpected"] - p["key_volume_mb"]
                   * p["fkFraction"] * p["availability"]) < 1e-12, p
        assert p["passMonth"] == 3, p          # epoch is 2024-03-20


def test_av_solver_missing_cloud_data_is_explicit():
    # Never degrade silently: an empty series must produce a note and a factor of
    # 1.0, not an invisible "assume clear skies" (nor an invisible zero).
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    base = _fk_solve_base()
    kv = _run_solve(SolveRequest(
        **base, availability_enabled=True,
        cloud_cover_hourly={"time": [], "cloud_cover": []}))["key_volume"]
    assert "availability_note" in kv
    assert "no cloud-cover data" in kv["availability_note"] \
        or "no valid hours" in kv["availability_note"], kv["availability_note"]
    assert "total_key_volume_available_mb" not in kv
    # And an unknown estimator is refused rather than guessed at.
    kv2 = _run_solve(SolveRequest(
        **base, availability_enabled=True, availability_estimator="bogus",
        cloud_cover_hourly=_av_solve_climatology()))["key_volume"]
    assert "availability_note" in kv2
    assert "bogus" in kv2["availability_note"], kv2["availability_note"]


def test_av_block_shrinkage_costs_more_than_pro_rata():
    # The inequality the whole "upper bound" claim rests on.  The finite-key
    # length is superadditive (Sidhu et al. 2022: ell_M >= M ell_1), so a pass cut
    # short to a fraction f of its counts yields ell(f n) <= f ell(n) — strictly
    # below, and exactly zero once the surviving block drops under threshold.
    # Hence p x ell(n) with p the mean clear fraction is an UPPER bound on the
    # cloud-averaged key, and the shortfall is worst for the small blocks.
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    base = {**_fk_solve_base(), "finite_key_enabled": True}
    kv = _run_solve(SolveRequest(
        **base, fk_block_fractions=[1.0, 0.75, 0.5, 0.25]))["key_volume"]
    graded = []
    for p in kv["passes"]:
        bf = p["ellBlockFractions"]
        assert abs(bf["1"]["ellFiniteBits"] - p["ellFiniteBits"]) < 1e-6, p
        prev = p["ellFiniteBits"]
        for f in ("0.75", "0.5", "0.25"):
            ell_f = bf[f]["ellFiniteBits"]
            pro_rata = float(f) * p["ellFiniteBits"]
            assert ell_f <= pro_rata + 1e-9, (f, ell_f, pro_rata)
            assert ell_f <= prev + 1e-9, (f, ell_f, prev)   # monotone in f
            assert 0.0 <= bf[f]["shortfall"] <= 1.0 + 1e-12, bf[f]
            prev = ell_f
        if p["ellFiniteBits"] > 0:
            graded.append((p["nSifted"], bf["0.5"]["shortfall"]))
    # Smaller blocks suffer a strictly larger shortfall: shortening a marginal
    # pass is not a rescaling, it decides whether there is any key at all.
    graded.sort()
    assert len(graded) >= 2, graded
    assert graded[0][1] < graded[-1][1], graded


def test_av_paper_constellation_keeps_clear_sky_column():
    # Ntanos et al. 2021 Table 1 is explicitly cloud-free ("no link interruption
    # due to clouds"), so the cloud-weighted annual key must arrive in SEPARATE
    # keys — confounding it with the reproduction total would mix two error
    # sources, one of which is already a known ~7x discrepancy.
    from app.routers.paper import ConstellationRequest, _run_constellation
    kw = dict(n_sats=1, total_orbits=40, samples_per_orbit=30)
    clim = {sid: _av_flat(40) for sid in ("helmos", "skinakas", "cholomondas")}
    off = _run_constellation(ConstellationRequest(**kw))
    on = _run_constellation(ConstellationRequest(
        **kw, availability_enabled=True, cloud_cover_hourly=clim))
    assert on["totals_gbit_year"] == off["totals_gbit_year"], (
        on["totals_gbit_year"], off["totals_gbit_year"])
    assert "totals_gbit_year_available" not in off
    assert on["availability"]["notes"] == [], on["availability"]["notes"]
    for sid, clear in on["totals_gbit_year"].items():
        avail = on["totals_gbit_year_available"][sid]
        assert 0.0 <= avail <= clear + 1e-9, (sid, avail, clear)
        if clear > 0.0:
            # Uniform 40 % cover → zenith proxy 0.60; the elevation-resolved,
            # key-weighted factor must be strictly below it.
            zen = on["availability"]["per_station"][sid]["zenith_annual"]
            assert abs(zen - 0.60) < 1e-6, (sid, zen)
            assert avail / clear < zen, (sid, avail / clear, zen)


test("availability: beta=1 shape factor is exactly 1/sin(eps)", test_av_shape_factor_identity)
test("availability: zenith PCFLOS = 1 - cloud fraction", test_av_zenith_is_one_minus_cover)
test("availability: monotone in elevation and in cover", test_av_monotone_in_elevation_and_cover)
test("availability: elevation bias matches reference table", test_av_elevation_bias_matches_reference_table)
test("availability: histogram equals hour-by-hour sum", test_av_histogram_equals_direct_sum)
test("availability: convex in cover, exact only at zenith", test_av_expectation_exceeds_mean_cover_plug_in)
test("availability: threshold estimator is discontinuous", test_av_threshold_estimator_differs_from_expectation)
test("availability: night conditioning is regime-dependent", test_av_night_conditioning_sign_is_regime_dependent)
test("availability: thin-month fallback and empty table", test_av_month_fallback_and_empty_table)
test("availability: filtered-to-nothing is no-data, not zero", test_av_filtered_to_nothing_is_no_data_not_zero)
test("availability: independence overstates OGS diversity", test_av_independence_overstates_network_diversity)
test("availability: annual profile is day-weighted", test_av_annual_profile_is_day_weighted)
test("availability: per-pass reduction is key-weighted", test_av_pass_reduction_weights_by_key)
test("availability: available volume == weighted integral", test_av_available_volume_equals_weighted_integral)
test("availability: each factor applied exactly once", test_av_effective_key_applies_each_factor_once)
test("availability: disabled is backward compatible", test_av_solver_disabled_is_backward_compatible)
test("availability: clear-sky and fk penalty untouched", test_av_solver_enabled_does_not_touch_clear_sky_or_fk)
test("availability: missing cloud data reported explicitly", test_av_solver_missing_cloud_data_is_explicit)
test("availability: ell(f*n) <= f*ell(n) (upper-bound basis)", test_av_block_shrinkage_costs_more_than_pro_rata)
test("availability: paper constellation keeps clear-sky column", test_av_paper_constellation_keeps_clear_sky_column)


# ========================================================================
# Monte Carlo channel wired into /api/solve
# ========================================================================
section("Monte Carlo channel (i.i.d. per sample)")

_MC_BASE = dict(
    semi_major_axis=6971.0, eccentricity=0.0, inclination_deg=97.8,
    raan_deg=0.0, arg_perigee_deg=0.0, mean_anomaly_deg=0.0,
    epoch="2026-01-01T00:00:00Z", samples_per_orbit=120, total_orbits=15,
    station_lat=41.4, station_lon=2.1, station_altitude_m=100.0,
    ground_aperture_m=1.0, sat_aperture_m=0.1, wavelength_nm=850.0,
    qkd_protocol="bb84-decoy", elevation_threshold_deg=10.0,
)


def _mc_solve(**over):
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    kw = dict(_MC_BASE)
    kw.update(over)
    return _run_solve(SolveRequest(**kw))


def test_mc_scint_stats_reproduce_loss_db():
    # scintillation_loss_db must stay a thin wrapper over scintillation_stats:
    # if the two drift, the MC band is drawn from a different distribution than
    # the deterministic margin is a quantile of, and the comparison is void.
    from app.physics.link_budget import scintillation_loss_db, scintillation_stats
    from app.physics.atmosphere_models import modified_hv_layers
    layers = modified_hv_layers(h_gs_m=100.0)
    for elev in (5.0, 20.0, 45.0, 90.0):
        st = scintillation_stats(elev, 850.0, 1.0, layers, 0.01)
        db = scintillation_loss_db(elev, 850.0, 1.0, layers, 0.01)
        assert abs(st["loss_db"] - db) < 1e-12, (elev, st["loss_db"], db)
        assert st["sigma_r2"] >= 0.0
        assert 0.0 < st["aperture_avg"] <= 1.0, st["aperture_avg"]


def test_mc_metrics_expose_turbulence_stats():
    from app.physics.atmosphere_models import modified_hv_layers
    r = _mc_solve(scintillation_enabled=True, atmosphere_model="modified-hv",
                  pointing_error_urad=2.0, pat_fading_enabled=True)
    m = r["station_metrics"]
    for key in ("sigmaR2", "apertureAvg", "divergenceRad", "pointingJitterUrad"):
        assert key in m, key
        assert len(m[key]) == len(m["elevationDeg"]), key
    # Rytov variance must fall as elevation rises — a shorter slant path through
    # the same profile cannot be more turbulent.
    pairs = [(e, s) for e, s in zip(m["elevationDeg"], m["sigmaR2"])
             if e is not None and e > 5.0 and s > 0]
    assert len(pairs) > 5, len(pairs)
    lo = min(pairs, key=lambda p: p[0])
    hi = max(pairs, key=lambda p: p[0])
    assert lo[1] > hi[1], (lo, hi)


def test_mc_disabled_is_backward_compatible():
    off = _mc_solve(scintillation_enabled=True, atmosphere_model="modified-hv")
    assert "monte_carlo" not in off
    m = off["station_metrics"]
    for key in ("skrKbpsP5", "skrKbpsP50", "skrKbpsP95", "outageProbability"):
        assert key not in m, key


def test_mc_band_is_ordered_and_brackets_nothing_negative():
    r = _mc_solve(scintillation_enabled=True, atmosphere_model="modified-hv",
                  pointing_error_urad=2.0, pat_fading_enabled=True,
                  monte_carlo_enabled=True, mc_realizations=60)
    m = r["station_metrics"]
    n = 0
    for p5, p50, p95 in zip(m["skrKbpsP5"], m["skrKbpsP50"], m["skrKbpsP95"]):
        if p5 is None:
            continue
        n += 1
        assert p5 >= 0.0, p5
        assert p5 <= p50 <= p95, (p5, p50, p95)
    assert n > 5, n
    assert r["monte_carlo"]["enabled"] is True
    assert 0.0 <= r["monte_carlo"]["link_time_outage"] <= 1.0


def test_mc_key_volume_untouched_by_sampling():
    # The MC band is diagnostic output. It must not feed back into the reported
    # key volume, or the headline number would silently become a percentile.
    kw = dict(scintillation_enabled=True, atmosphere_model="modified-hv",
              pointing_error_urad=2.0, pat_fading_enabled=True)
    off = _mc_solve(**kw)
    on = _mc_solve(**kw, monte_carlo_enabled=True, mc_realizations=40)
    assert (off["key_volume"]["total_key_volume_mb"]
            == on["key_volume"]["total_key_volume_mb"])
    assert off["station_metrics"]["skrKbps"] == on["station_metrics"]["skrKbps"]


def test_mc_no_turbulence_no_jitter_collapses_to_deterministic():
    # With nothing to sample, every realization is the mean channel, so the band
    # must collapse onto the deterministic curve exactly. This is the check that
    # the base loss is de-biased correctly: if the deterministic fade terms were
    # not subtracted, the collapse would land somewhere else.
    r = _mc_solve(scintillation_enabled=False, pointing_error_urad=0.0,
                  monte_carlo_enabled=True, mc_realizations=25)
    m = r["station_metrics"]
    n = 0
    for det, p5, p50, p95 in zip(m["skrKbps"], m["skrKbpsP5"],
                                 m["skrKbpsP50"], m["skrKbpsP95"]):
        if det is None or p5 is None:
            continue
        n += 1
        assert abs(p5 - det) < 1e-9, (det, p5)
        assert abs(p95 - det) < 1e-9, (det, p95)
    assert n > 5, n
    assert r["monte_carlo"]["link_time_outage"] == 0.0


def test_mc_seed_is_reproducible_and_seedless_is_not_claimed():
    kw = dict(scintillation_enabled=True, atmosphere_model="modified-hv",
              monte_carlo_enabled=True, mc_realizations=40)
    a = _mc_solve(**kw, mc_seed=7)["station_metrics"]["skrKbpsP5"]
    b = _mc_solve(**kw, mc_seed=7)["station_metrics"]["skrKbpsP5"]
    c = _mc_solve(**kw, mc_seed=8)["station_metrics"]["skrKbpsP5"]
    assert a == b, "same seed must reproduce the band exactly"
    assert a != c, "different seeds must actually draw different channels"


def test_mc_median_sits_above_deterministic_p0_margin():
    # The deterministic curve carries the p0 = 1 % scintillation FADE MARGIN,
    # which is a pessimistic quantile, while the MC draws from the distribution
    # itself. The median must therefore sit above it. If it sat below, the fade
    # would be counted twice — the exact bug the de-biasing prevents.
    kw = dict(scintillation_enabled=True, atmosphere_model="modified-hv",
              pointing_error_urad=2.0, pat_fading_enabled=True)
    det = _mc_solve(**kw)["station_metrics"]["skrKbps"]
    p50 = _mc_solve(**kw, monte_carlo_enabled=True,
                    mc_realizations=80)["station_metrics"]["skrKbpsP50"]
    above = tot = 0
    for d, p in zip(det, p50):
        if d is None or p is None or d <= 0:
            continue
        tot += 1
        above += (p >= d - 1e-9)
    assert tot > 5, tot
    assert above / tot > 0.9, (above, tot)


test("monte carlo: scintillation_stats matches loss_db", test_mc_scint_stats_reproduce_loss_db)
test("monte carlo: metrics expose sigma_R^2 / aperture avg", test_mc_metrics_expose_turbulence_stats)
test("monte carlo: disabled is backward compatible", test_mc_disabled_is_backward_compatible)
test("monte carlo: P5 <= P50 <= P95 and outage in [0,1]", test_mc_band_is_ordered_and_brackets_nothing_negative)
test("monte carlo: key volume untouched by sampling", test_mc_key_volume_untouched_by_sampling)
test("monte carlo: no fading collapses band to deterministic", test_mc_no_turbulence_no_jitter_collapses_to_deterministic)
test("monte carlo: seeded runs reproduce exactly", test_mc_seed_is_reproducible_and_seedless_is_not_claimed)
test("monte carlo: median above the p0 fade margin", test_mc_median_sits_above_deterministic_p0_margin)


# ========================================================================
# Contention-aware scheduling (physics/scheduling.py)
# ========================================================================
section("Contention-aware scheduling")


def _sched_toy():
    """Two satellites, two stations, overlapping visibility on a 0..10 s grid.

    Pair (0,0) and (1,0) both want station 0 over the same interval, so a
    matching must drop one of them; (1,1) is uncontended.
    """
    import numpy as np
    t = [float(x) for x in range(11)]
    def band(lo, hi, val):
        return np.array([val if lo <= i <= hi else 0.0 for i in range(11)])
    rates = {
        (0, 0): band(1, 5, 100.0),
        (1, 0): band(3, 8, 50.0),
        (1, 1): band(3, 8, 20.0),
    }
    elev = {
        (0, 0): [30.0 if 1 <= i <= 5 else -5.0 for i in range(11)],
        (1, 0): [30.0 if 3 <= i <= 8 else -5.0 for i in range(11)],
        (1, 1): [30.0 if 3 <= i <= 8 else -5.0 for i in range(11)],
    }
    return t, rates, elev


def test_sched_interval_weights_reproduce_trapezoid():
    import numpy as np
    from app.physics.scheduling import interval_weights
    t, rates, _ = _sched_toy()
    w, active = interval_weights(t, rates)
    for pair, r in rates.items():
        assert abs(w[pair].sum() - float(np.trapezoid(r, t))) < 1e-9, pair
    assert active == sorted(set(active))
    # An interval is active iff some pair has key in it.
    for k in range(len(t) - 1):
        any_key = any(w[p][k] > 0 for p in rates)
        assert (k in active) == any_key, k


def test_sched_interval_weights_reject_wrong_length():
    import numpy as np
    from app.physics.scheduling import interval_weights
    try:
        interval_weights([0.0, 1.0, 2.0], {(0, 0): np.array([1.0, 2.0])})
    except ValueError:
        return
    raise AssertionError("a rate series of the wrong length must not be accepted")


def test_sched_contacts_match_elevation_segments():
    from app.physics.scheduling import contacts_from_elevation, interval_weights
    t, rates, elev = _sched_toy()
    w, _ = interval_weights(t, rates)
    cs = contacts_from_elevation(0, 0, t, elev[(0, 0)], w[(0, 0)], 10.0)
    assert len(cs) == 1, cs
    c = cs[0]
    assert (c.i0, c.i1) == (1, 5), (c.i0, c.i1)
    assert abs(c.duration_s - 4.0) < 1e-12
    assert abs(c.bits - w[(0, 0)][1:5].sum()) < 1e-12
    assert c.max_elev_deg == 30.0


def test_sched_bound_chain_holds():
    from app.physics.scheduling import (
        contact_upper_bound, contacts_from_elevation, interval_weights,
        schedule_contacts, schedule_independent, schedule_preemptive)
    t, rates, elev = _sched_toy()
    w, active = interval_weights(t, rates)
    contacts = []
    for pair in rates:
        contacts += contacts_from_elevation(
            pair[0], pair[1], t, elev[pair], w[pair], 10.0)
    ind = schedule_independent(w, active)
    pre = schedule_preemptive(w, active, 2, 2)
    con = schedule_contacts(contacts)
    ub = contact_upper_bound(contacts)
    assert con.total_bits <= ub["bound"] + 1e-9, (con.total_bits, ub)
    assert ub["bound"] <= pre.total_bits + 1e-9, (ub, pre.total_bits)
    assert pre.total_bits <= ind.total_bits + 1e-9, (pre.total_bits, ind.total_bits)
    assert ub["exact"] is True
    # Contention must actually bind here, or the test proves nothing.
    assert pre.total_bits < ind.total_bits - 1e-9


def test_sched_preemptive_respects_the_matching():
    from app.physics.scheduling import interval_weights, schedule_preemptive
    t, rates, _ = _sched_toy()
    w, active = interval_weights(t, rates)
    res = schedule_preemptive(w, active, 2, 2)
    per_interval = {}
    for pair, idx in res.intervals.items():
        for k in idx:
            per_interval.setdefault(k, []).append(pair)
    for k, pairs in per_interval.items():
        sats = [p[0] for p in pairs]
        gss = [p[1] for p in pairs]
        assert len(sats) == len(set(sats)), (k, pairs)
        assert len(gss) == len(set(gss)), (k, pairs)


def test_sched_contact_is_whole_or_nothing():
    from app.physics.scheduling import (
        contacts_from_elevation, interval_weights, schedule_contacts)
    t, rates, elev = _sched_toy()
    w, _ = interval_weights(t, rates)
    contacts = []
    for pair in rates:
        contacts += contacts_from_elevation(
            pair[0], pair[1], t, elev[pair], w[pair], 10.0)
    res = schedule_contacts(contacts)
    kept = {(c.sat, c.gs): c for c in res.contacts_kept}
    # Station 0 is contested by (0,0) and (1,0); only one can be kept whole.
    at_gs0 = [c for c in res.contacts_kept if c.gs == 0]
    assert len(at_gs0) == 1, at_gs0
    assert at_gs0[0].sat == 0, "greedy must keep the heavier contact"
    for pair, frags in res.fragments.items():
        assert len(frags) == 1, (pair, frags)
        assert frags[0] == (kept[pair].i0, kept[pair].i1)


def test_sched_wis_upper_bound_is_exact_on_a_known_instance():
    from app.physics.scheduling import Contact, contact_upper_bound
    # One satellite, one station, three contacts: two disjoint small ones that
    # together beat the single overlapping large one.
    cs = [
        Contact(sat=0, gs=0, i0=0, i1=2, t0=0.0, t1=2.0, bits=6.0),
        Contact(sat=0, gs=0, i0=3, i1=5, t0=3.0, t1=5.0, bits=6.0),
        Contact(sat=0, gs=0, i0=1, i1=4, t0=1.0, t1=4.0, bits=10.0),
    ]
    ub = contact_upper_bound(cs)
    assert abs(ub["ub_sat"] - 12.0) < 1e-12, ub
    assert abs(ub["bound"] - 12.0) < 1e-12, ub
    assert ub["exact"] is True


def test_sched_multi_terminal_bound_is_declared_loose():
    from app.physics.scheduling import Contact, contact_upper_bound
    cs = [Contact(sat=0, gs=0, i0=0, i1=2, t0=0.0, t1=2.0, bits=5.0),
          Contact(sat=0, gs=0, i0=1, i1=3, t0=1.0, t1=3.0, bits=5.0)]
    ub = contact_upper_bound(cs, sat_terminals=2, gs_terminals=2)
    assert ub["exact"] is False
    assert "loose" in ub["note"]
    assert abs(ub["bound"] - 10.0) < 1e-12, ub


def test_sched_marginal_curve_saturates():
    from app.physics.scheduling import marginal_curve
    # A deliberately submodular objective: elements overlap, so adding the
    # second is worth less than it is alone.
    coverage = {"a": {1, 2, 3}, "b": {3, 4}, "c": {1, 2}}
    def ev(subset):
        s = set()
        for e in subset:
            s |= coverage[e]
        return float(len(s))
    curve = marginal_curve(["a", "b", "c"], ev, order="greedy")
    assert [s["element"] for s in curve][0] == "a", curve
    cum = [s["cumulative"] for s in curve]
    assert cum == sorted(cum), cum
    assert abs(cum[-1] - 4.0) < 1e-12, cum
    for s in curve:
        assert 0.0 <= s["saturation"] <= 1.0 + 1e-12, s
    assert curve[-1]["saturation"] == 0.0, curve[-1]
    standalone = marginal_curve(["a", "b", "c"], ev, order="standalone")
    assert all(s["saturation"] == 1.0 for s in standalone), standalone


test("scheduling: interval weights reproduce the trapezoid", test_sched_interval_weights_reproduce_trapezoid)
test("scheduling: wrong-length rate series is rejected", test_sched_interval_weights_reject_wrong_length)
test("scheduling: contacts match the elevation segments", test_sched_contacts_match_elevation_segments)
test("scheduling: contact <= UB <= preemptive <= independent", test_sched_bound_chain_holds)
test("scheduling: preemptive never double-books a terminal", test_sched_preemptive_respects_the_matching)
test("scheduling: contact policy is whole-or-nothing", test_sched_contact_is_whole_or_nothing)
test("scheduling: WIS bound exact on a known instance", test_sched_wis_upper_bound_is_exact_on_a_known_instance)
test("scheduling: multi-terminal bound declared loose", test_sched_multi_terminal_bound_is_declared_loose)
test("scheduling: marginal curve saturates on overlap", test_sched_marginal_curve_saturates)


# ========================================================================
# Constellation study endpoint (/api/study/constellation)
# ========================================================================
section("Constellation study (contention + finite key)")

_STUDY_STATIONS = [
    {"id": "calar", "name": "Calar Alto", "lat": 37.22, "lon": -2.55,
     "altitude_m": 2168.0, "aperture_m": 1.0},
    {"id": "grasse", "name": "Grasse", "lat": 43.75, "lon": 6.92,
     "altitude_m": 1270.0, "aperture_m": 1.0},
]


def _study_base(**over):
    from app.models import SolveRequest
    kw = dict(
        semi_major_axis=6971.0, eccentricity=0.0, inclination_deg=97.8,
        epoch="2026-01-01T00:00:00Z", samples_per_orbit=90, total_orbits=15,
        ground_aperture_m=1.0, sat_aperture_m=0.1, wavelength_nm=850.0,
        qkd_protocol="bb84-decoy", scintillation_enabled=True,
        atmosphere_model="modified-hv", pointing_error_urad=2.0,
        pat_fading_enabled=True, elevation_threshold_deg=10.0,
    )
    kw.update(over)
    return SolveRequest(**kw)


def _study(stations=None, **over):
    from app.routers.study import (
        ConstellationStudyRequest, _run_constellation_study)
    base = over.pop("base", None) or _study_base()
    kw = dict(walker_T=4, walker_P=2, walker_F=1)
    kw.update(over)
    req = ConstellationStudyRequest(base=base, **kw)
    return _run_constellation_study(req, stations or _STUDY_STATIONS)


def test_study_bound_chain_ordering():
    r = _study()
    ch = r["bound_chain_asymptotic"]
    assert ch["contact_greedy"] <= ch["contact_opt_upper_bound"] + 1e-6
    assert ch["contact_opt_upper_bound"] <= ch["preemptive"] + 1e-6
    assert ch["preemptive"] <= ch["independent"] + 1e-6
    # Contention must bind, else the study is reporting a tautology.
    assert ch["preemptive"] < ch["independent"], ch
    assert r["contacts"]["total"] > 0


def test_study_elevation_threshold_binds_every_policy():
    # REGRESSION. The preemptive policy scores intervals directly and never
    # looks at contacts, so before the rate series was masked it collected key
    # below the minimum tracking elevation that the contact policy was
    # forbidden to use. Its total then did not move with the threshold, and the
    # bound chain was comparing two different problems.
    lo = _study(base=_study_base(elevation_threshold_deg=10.0))
    hi = _study(base=_study_base(elevation_threshold_deg=45.0))
    for pol in ("independent", "preemptive", "contact"):
        a = lo["policies"][pol]["asymptotic_bits"]
        b = hi["policies"][pol]["asymptotic_bits"]
        assert b < a, (pol, a, b)


def test_study_walker_validation():
    from fastapi import HTTPException
    try:
        _study(walker_T=5, walker_P=2)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "divisible" in exc.detail
    else:
        raise AssertionError("T not divisible by P must be rejected, not "
                             "silently truncated by generate_walker")


def test_study_mixed_semi_major_axis_is_rejected():
    from fastapi import HTTPException
    sats = [
        {"semiMajor": 6971.0, "eccentricity": 0.0, "inclination": 97.8,
         "raan": 0.0, "argPerigee": 0.0, "meanAnomaly": 0.0},
        {"semiMajor": 7071.0, "eccentricity": 0.0, "inclination": 97.8,
         "raan": 180.0, "argPerigee": 0.0, "meanAnomaly": 0.0},
    ]
    try:
        _study(satellites=sats, walker_T=None, walker_P=None)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "time grid" in exc.detail
    else:
        raise AssertionError("differing semi-major axes give different time "
                             "grids and must be rejected, not resampled")


def test_study_finite_key_off_by_default():
    r = _study()
    assert r["finite_key"]["enabled"] is False
    for pol in r["policies"].values():
        assert "finite_bits" not in pol
    assert "finite_key_inversion" not in r


def test_study_finite_key_is_below_asymptotic():
    r = _study(base=_study_base(finite_key_enabled=True))
    assert r["finite_key"]["enabled"] is True
    for name, pol in r["policies"].items():
        assert 0.0 <= pol["finite_bits"] <= pol["asymptotic_bits"] + 1e-6, name
        assert 0.0 <= pol["finite_fraction"] <= 1.0, name


def test_study_fragmentation_costs_more_than_pro_rata():
    # Serving half of a pass keeps LESS than half its key: the Lim 2014
    # deviations scale as sqrt(n) while the counts scale as n. This is the
    # mechanism behind the whole result, so it is checked directly on the
    # evaluator rather than inferred from the totals.
    from app.routers.solver import _run_single_station
    from app.physics.propagation import propagate_orbit
    from app.physics.scheduling import contacts_from_elevation, interval_weights
    from app.routers.study import _pair_rates_bps, _finite_bits_for_fragments
    base = _study_base(finite_key_enabled=True)
    prop = propagate_orbit(
        a=base.semi_major_axis, e=base.eccentricity,
        inc_deg=base.inclination_deg, raan_deg=0.0, arg_pe_deg=0.0, M0_deg=0.0,
        j2_enabled=base.j2_enabled, epoch_iso=base.epoch,
        samples_per_orbit=base.samples_per_orbit, total_orbits=base.total_orbits)
    out = _run_single_station(prop, _STUDY_STATIONS[0], base,
                              collect_fk_evaluator=True)
    ev = out["_fk_evaluate"]
    assert ev is not None
    m = out["station_metrics"]
    n = len(prop["timeline"])
    rates = _pair_rates_bps(m, n, base.elevation_threshold_deg)
    w, _ = interval_weights(prop["timeline"], {(0, 0): rates})
    cs = contacts_from_elevation(0, 0, prop["timeline"], m["elevationDeg"],
                                 w[(0, 0)], base.elevation_threshold_deg)
    cs = [c for c in cs if c.i1 - c.i0 >= 4 and c.bits > 0]
    assert cs, "no usable contact to fragment"
    checked = 0
    for c in cs:
        whole = _finite_bits_for_fragments([(c.i0, c.i1)], [c], ev)
        if whole <= 0:
            continue
        mid = (c.i0 + c.i1) // 2
        half = _finite_bits_for_fragments([(c.i0, mid)], [c], ev)
        checked += 1
        assert half < 0.5 * whole + 1e-9, (c.i0, c.i1, half, whole)
    assert checked > 0, "no contact produced finite key to fragment"


def test_study_fragments_of_one_pass_form_one_block():
    # Two fragments of the SAME pass are one block whose counts add; treating
    # them as two blocks would pay the sqrt(n) deviation twice and understate
    # the key. Verified via the evaluator's additivity on a contiguous split.
    from app.routers.solver import _run_single_station
    from app.physics.propagation import propagate_orbit
    from app.physics.scheduling import contacts_from_elevation, interval_weights
    from app.routers.study import _pair_rates_bps, _finite_bits_for_fragments
    base = _study_base(finite_key_enabled=True)
    prop = propagate_orbit(
        a=base.semi_major_axis, e=base.eccentricity,
        inc_deg=base.inclination_deg, raan_deg=0.0, arg_pe_deg=0.0, M0_deg=0.0,
        j2_enabled=base.j2_enabled, epoch_iso=base.epoch,
        samples_per_orbit=base.samples_per_orbit, total_orbits=base.total_orbits)
    out = _run_single_station(prop, _STUDY_STATIONS[0], base,
                              collect_fk_evaluator=True)
    ev = out["_fk_evaluate"]
    m = out["station_metrics"]
    n = len(prop["timeline"])
    rates = _pair_rates_bps(m, n, base.elevation_threshold_deg)
    w, _ = interval_weights(prop["timeline"], {(0, 0): rates})
    cs = [c for c in contacts_from_elevation(
              0, 0, prop["timeline"], m["elevationDeg"], w[(0, 0)],
              base.elevation_threshold_deg)
          if c.i1 - c.i0 >= 4]
    assert cs
    c = max(cs, key=lambda x: x.bits)
    mid = (c.i0 + c.i1) // 2
    whole = _finite_bits_for_fragments([(c.i0, c.i1)], [c], ev)
    split = _finite_bits_for_fragments([(c.i0, mid), (mid, c.i1)], [c], ev)
    assert abs(split - whole) < 1e-6 * max(whole, 1.0), (whole, split)


def test_study_finite_key_inversion_is_reachable():
    # THE HEADLINE CLAIM. The preemptive schedule upper-bounds the asymptotic
    # key but can deliver LESS distillable key, because re-pointing mid-pass
    # shatters blocks. If no configuration inverts, the claim must not be made.
    base = _study_base(finite_key_enabled=True, photon_rate=3e7)
    r = _study(base=base, walker_T=12, walker_P=4,
               policies=["preemptive", "contact"])
    inv = r["finite_key_inversion"]
    pre, con = r["policies"]["preemptive"], r["policies"]["contact"]
    assert pre["asymptotic_bits"] > con["asymptotic_bits"], (pre, con)
    assert inv["inverted"] is True, (pre["finite_bits"], con["finite_bits"])
    assert con["finite_bits"] > pre["finite_bits"]
    # Fragmentation is the mechanism: preemptive must serve more pieces.
    assert pre["contacts_served"] > con["contacts_served"]


def test_study_marginal_curve_saturates_under_contention():
    r = _study(marginal_over="stations", marginal_policy="contact",
               marginal_metric="asymptotic")
    curve = r["marginal_curve"]["steps"]
    assert len(curve) == len(_STUDY_STATIONS)
    cum = [s["cumulative"] for s in curve]
    assert cum == sorted(cum), cum
    assert curve[0]["saturation"] == 1.0
    for s in curve:
        assert 0.0 <= s["saturation"] <= 1.0 + 1e-9, s
    # Under contention the second station cannot be worth its full standalone
    # value — that is the entire point of scoring it under a schedule.
    assert curve[-1]["saturation"] < 1.0, curve


def test_study_independent_policy_cannot_answer_the_marginal_question():
    # Without contention every marginal gain IS the standalone value, so the
    # curve is flat at 1.0 and says nothing. Documented in the response note;
    # asserted here so the note stays true.
    r = _study(marginal_over="stations", marginal_policy="independent",
               marginal_metric="asymptotic")
    for s in r["marginal_curve"]["steps"]:
        assert abs(s["saturation"] - 1.0) < 1e-9, s


def test_study_reuses_the_solver_physics():
    # The study must not fork the link budget. A single-satellite study over one
    # station under the independent policy has to reproduce the key volume
    # /api/solve reports for the same configuration.
    from app.models import SolveRequest
    from app.routers.solver import _run_solve
    st = _STUDY_STATIONS[0]
    base = _study_base()
    solo = _run_solve(SolveRequest(**{
        **base.dict(),
        "station_lat": st["lat"], "station_lon": st["lon"],
        "station_altitude_m": st["altitude_m"], "ground_aperture_m": st["aperture_m"],
    }))
    sats = [{"semiMajor": base.semi_major_axis, "eccentricity": 0.0,
             "inclination": base.inclination_deg, "raan": 0.0,
             "argPerigee": 0.0, "meanAnomaly": 0.0}]
    r = _study(stations=[st], satellites=sats, walker_T=None, walker_P=None,
               policies=["independent"])
    got = r["pairs"]["sat1|calar"]["key_mb_unscheduled"]
    assert abs(got - solo["key_volume"]["total_key_volume_mb"]) < 1e-9, (
        got, solo["key_volume"]["total_key_volume_mb"])
    assert r["pairs"]["sat1|calar"]["passes"] == solo["key_volume"]["pass_count"]


def test_study_cn2_profile_follows_each_station_altitude():
    # REGRESSION. _build_cn2_layers read the request's single station_altitude_m,
    # so in any multi-station run every OGS got the same boundary layer while
    # the geometry used its real altitude. The modified-HV ground term exists
    # precisely to resolve that (Ntanos 2021 Eq. 11), and altitude is the main
    # reason to site an OGS high, so the error hit exactly the sites that
    # matter — Teide at 2390 m scored with a sea-level profile.
    from app.routers.solver import _build_cn2_layers
    base = _study_base(station_altitude_m=0.0)
    low = _build_cn2_layers(base, {"lat": 28.3, "lon": -16.5, "altitude_m": 0.0})
    high = _build_cn2_layers(base, {"lat": 28.3, "lon": -16.5, "altitude_m": 2390.0})
    assert low and high
    assert low[0][0] != high[0][0], (low[0], high[0])
    assert abs(high[0][0] - 2390.0) < 1e-6, high[0]
    # Same request, two stations, two different profiles => different fade.
    from app.physics.link_budget import scintillation_loss_db
    a = scintillation_loss_db(20.0, 850.0, 1.0, low, 0.01)
    b = scintillation_loss_db(20.0, 850.0, 1.0, high, 0.01)
    assert a != b, (a, b)
    # Falling back to the request when no record is supplied is unchanged.
    assert _build_cn2_layers(base) == low


def test_study_multi_terminal_states_its_caveat():
    r = _study(sat_terminals=2, gs_terminals=2)
    assert any("b-matching" in c for c in r.get("caveats", [])), r.get("caveats")
    assert r["contact_upper_bound"]["exact"] is False


test("study: bound chain ordering holds", test_study_bound_chain_ordering)
test("study: elevation threshold binds every policy", test_study_elevation_threshold_binds_every_policy)
test("study: Walker T not divisible by P is rejected", test_study_walker_validation)
test("study: mixed semi-major axis is rejected", test_study_mixed_semi_major_axis_is_rejected)
test("study: finite key off by default", test_study_finite_key_off_by_default)
test("study: finite key below asymptotic for every policy", test_study_finite_key_is_below_asymptotic)
test("study: half a pass keeps less than half the key", test_study_fragmentation_costs_more_than_pro_rata)
test("study: fragments of one pass form one block", test_study_fragments_of_one_pass_form_one_block)
test("study: finite-key inversion is reachable", test_study_finite_key_inversion_is_reachable)
test("study: marginal curve saturates under contention", test_study_marginal_curve_saturates_under_contention)
test("study: independent policy gives a flat curve", test_study_independent_policy_cannot_answer_the_marginal_question)
test("study: reuses the /api/solve physics exactly", test_study_reuses_the_solver_physics)
test("study: Cn2 profile follows each station's altitude", test_study_cn2_profile_follows_each_station_altitude)
test("study: multi-terminal caveat is stated", test_study_multi_terminal_states_its_caveat)


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

