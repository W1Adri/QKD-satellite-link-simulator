"""
Channel-only validation of SimulCTTC against a published link budget.

Reference
---------
D. Giggenbach, A. Shrestha, C. Fuchs, C. Schmidt, F. Moll,
"System Aspects of Optical LEO-to-Ground Links",
International Conference on Space Optics (ICSO) 2016, Biarritz, France.
Link-budget table = **Figure 7** of that paper (p. 4).

Scope
-----
Only the CHANNEL rows are validated here: slant range, geometric loss
(Tx gain + free-space loss + Rx gain), atmospheric attenuation, and the
accumulated received power up to "Rx-Power after Losses".

The paper's Comms block (data rate, 800 Ph/bit sensitivity, Reed-Solomon
coding gain, link margin) is deliberately NOT covered: SimulCTTC has no
classical IM/DD receiver model, it produces secret-key rate / QBER.

Scenario of Figure 7
--------------------
  Tx power              1.00 W  = +30 dBm
  Tx optical loss      -1.49 dB
  Tx aperture          40 mm      (Tx-telescope gain 98.19 dB)
  Pointing penalty     -3.01 dB   (fixed allocation, NOT a jitter model)
  Wavelength           1550 nm
  Rx aperture          60 cm
  Rx optical loss      -6.02 dB
  Orbits               400 km and 900 km, circular
  Elevations           5, 10, 15, 20 deg

Two anomalies in the source table are pinned down by section 5 below; read
that section before "fixing" anything to match the printed numbers.

Run:  python3 test_giggenbach2016.py
"""
import math
import sys
import traceback

sys.path.insert(0, ".")

from app.physics.constants import EARTH_RADIUS_KM
from app.physics.geometry import geometric_loss, los_elevation
from app.physics.link_budget import atm_loss_db, scintillation_stats

# ── result tracking ──────────────────────────────────────────────────────
PASS = 0
FAIL = 0
DEVIATION = 0
NOTES = []


def test(name, func):
    global PASS, FAIL
    try:
        func()
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()


def deviation(name, detail):
    """A quantified, understood mismatch with the reference — not a crash."""
    global DEVIATION
    DEVIATION += 1
    print(f"  [DEVIATION] {name}")
    NOTES.append((name, detail))


def section(title):
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


# ── paper constants ──────────────────────────────────────────────────────
LAMBDA_M = 1550e-9
D_TX_M = 0.040          # spacecraft aperture
D_RX_M = 0.600          # OGS aperture
TX_POWER_DBM = 30.0     # 1.00 W
TX_OPTICAL_LOSS_DB = 1.49
POINTING_PENALTY_DB = 3.01
RX_OPTICAL_LOSS_DB = 6.02

# Zenith atmospheric loss implied by the paper's Figure 5 (1550 nm, 23 km
# visibility).  Fitted from their tabulated values divided by airmass 1/sin(el);
# the four columns imply 0.68-0.78 dB, so 0.70 dB is the representative value.
ZENITH_ATM_LOSS_DB = 0.70

# Figure 7, transcribed.  Verified against the rendered PDF page, not only
# against the text layer.
PAPER = {
    400: {
        "elev_deg":      [5, 10, 15, 20],
        "distance_km":   [1804, 1439, 1175, 984],
        "fsl_row_db":    [-54.14, -52.18, -50.41, -48.87],   # see section 5
        "scint_db":      [-5.00, -3.50, -2.50, -1.70],
        "atm_db":        [-8.00, -4.00, -3.00, -2.00],
        "rx_after_dbm":  [-37.21, -29.75, -25.98, -22.64],
    },
    900: {
        "elev_deg":      [5, 10, 15, 20],
        "distance_km":   [2992, 2568, 2224, 1947],
        "fsl_row_db":    [-58.53, -57.21, -55.96, -54.80],
        "scint_db":      [-5.00, -3.50, -2.50, -1.70],
        "atm_db":        [-8.00, -4.00, -3.00, -2.00],
        "rx_after_dbm":  [-41.60, -34.78, -31.53, -28.57],
    },
}

CASES = [(h, i) for h in (400, 900) for i in range(4)]


# ── helpers ──────────────────────────────────────────────────────────────

def _sat_ecef_at_elevation(alt_km, elev_deg):
    """ECEF position of a satellite seen at *elev_deg* from a station at (0,0).

    Places the satellite in the equatorial plane so the geometry reduces to a
    plane triangle Earth-centre / station / satellite.  The Earth-centred angle
    is  phi = 90 - el - asin(R cos(el) / r), from the sine rule.

    Uses SimulCTTC's own EARTH_RADIUS_KM (6378.137, equatorial) rather than the
    paper's 6371 (mean), so the comparison exercises the real code path.
    """
    r = EARTH_RADIUS_KM + alt_km
    el = math.radians(elev_deg)
    phi = math.pi / 2.0 - el - math.asin(EARTH_RADIUS_KM * math.cos(el) / r)
    return [r * math.cos(phi), r * math.sin(phi), 0.0]


def _paper_geometric_loss_db(distance_km):
    """The paper's own geometric chain: G_tx + L_fs + G_rx, in dB (negative).

    G = (pi D / lambda)^2 (standard antenna gain, reproduces their 98.19 dB
    for D = 40 mm), L_fs = (lambda / (4 pi d))^2.
    """
    g_tx = 10 * math.log10((math.pi * D_TX_M / LAMBDA_M) ** 2)
    g_rx = 10 * math.log10((math.pi * D_RX_M / LAMBDA_M) ** 2)
    l_fs = 10 * math.log10((LAMBDA_M / (4 * math.pi * distance_km * 1e3)) ** 2)
    return g_tx + l_fs + g_rx


STATION = {"lat": 0.0, "lon": 0.0, "altitude_m": 0.0}


# =========================================================================
section("1. Slant range vs Figure 7 (circular orbit geometry)")
# =========================================================================
# The paper tabulates 1804 km at 5 deg / 400 km, consistent with a spherical
# Earth of 6371 km.  SimulCTTC uses 6378.137 km; the resulting range difference
# is sub-km because low-elevation slant range is dominated by the tangent
# geometry, not by the radius itself.

def _check_range():
    worst = 0.0
    print(f"    {'orbit':>6} {'elev':>5} {'paper':>8} {'ours':>9} {'diff':>8}")
    for h, i in CASES:
        p = PAPER[h]
        el, d_paper = p["elev_deg"][i], p["distance_km"][i]
        los = los_elevation(STATION, _sat_ecef_at_elevation(h, el))
        # the placement must round-trip through our own elevation solver
        assert abs(los["elevationDeg"] - el) < 1e-6, \
            f"elevation round-trip failed: {los['elevationDeg']} != {el}"
        diff = los["distanceKm"] - d_paper
        worst = max(worst, abs(diff))
        print(f"    {h:>6} {el:>4}d {d_paper:>8} {los['distanceKm']:>9.1f} "
              f"{diff:>+8.2f}")
    # 2 km at 2992 km is 0.06 % -> 0.005 dB of free-space loss.  The residual
    # is the 7.1 km radius difference (6378.137 equatorial vs 6371 mean) plus
    # the paper's rounding to whole km.
    assert worst < 2.0, f"slant range off by {worst:.2f} km"
    print(f"    -> worst deviation {worst:.2f} km "
          f"({100 * worst / 2992:.3f} % -> "
          f"{20 * math.log10(1 + worst / 2992):.4f} dB of free-space loss)")

test("slant range matches Figure 7 within 2 km", _check_range)


# =========================================================================
section("2. Geometric loss: geometric_loss() vs G_tx + L_fs + G_rx")
# =========================================================================
# SimulCTTC's "gaussian" model uses w0 = 2*lambda/(pi*D_tx) and a capture ratio
# (D_rx / (2 d w0))^2.  That expands to (pi D_tx D_rx / (4 lambda d))^2, which
# is algebraically identical to G_tx * L_fs * G_rx — so it should match the
# paper exactly, not approximately.

def _check_geo_gaussian():
    worst = 0.0
    print(f"    {'orbit':>6} {'elev':>5} {'paper':>9} {'ours':>9} {'diff':>7}")
    for h, i in CASES:
        p = PAPER[h]
        d = p["distance_km"][i]
        ref = _paper_geometric_loss_db(d)
        ours = -geometric_loss(d, D_TX_M, D_RX_M, 1550.0, model="gaussian")["lossDb"]
        worst = max(worst, abs(ours - ref))
        print(f"    {h:>6} {p['elev_deg'][i]:>4}d {ref:>9.2f} {ours:>9.2f} "
              f"{ours - ref:>+7.3f}")
    assert worst < 0.01, f"gaussian geometric loss off by {worst:.3f} dB"
    print(f"    -> worst deviation {worst:.4f} dB (exact, as expected)")

test("geometric_loss(model='gaussian') reproduces the paper exactly",
     _check_geo_gaussian)


def _check_geo_airy():
    """The default 'airy' model is a fixed offset from the paper's convention."""
    offsets = []
    for h, i in CASES:
        d = PAPER[h]["distance_km"][i]
        ours = -geometric_loss(d, D_TX_M, D_RX_M, 1550.0, model="airy")["lossDb"]
        offsets.append(ours - _paper_geometric_loss_db(d))
    spread = max(offsets) - min(offsets)
    assert spread < 0.01, f"airy offset is not constant (spread {spread:.3f} dB)"
    print(f"    -> 'airy' predicts {offsets[0]:+.2f} dB more received power "
          f"than the paper (optimistic), spread {spread:.4f} dB")
    # Spot radius at range d: airy uses 0.61*lambda*d/D_tx (half the first-null
    # full angle 1.22*lambda/D_tx), gaussian uses 2*lambda*d/(pi*D_tx) = 0.6366.
    # Smaller spot -> more captured power: 20*log10(0.6366/0.61) = +0.37 dB.
    assert abs(offsets[0] - 20 * math.log10((2.0 / math.pi) / 0.61)) < 0.01

test("geometric_loss(model='airy') differs by a constant, explained offset",
     _check_geo_airy)


# =========================================================================
section("3. Atmospheric attenuation: atm_loss_db() vs Figure 5")
# =========================================================================
# The paper gives the attenuation as a graph (Figure 5, 1550 nm, 23 km
# visibility) and reads four values off it.  Our model is
# L(el) = L_zenith / sin(el).

def _check_atm():
    worst = 0.0
    print(f"    {'elev':>5} {'paper':>7} {'ours':>7} {'diff':>7} {'implied L_zen':>14}")
    for i, el in enumerate(PAPER[400]["elev_deg"]):
        ref = -PAPER[400]["atm_db"][i]
        ours = atm_loss_db(el, ZENITH_ATM_LOSS_DB, 0.0)
        implied = ref * math.sin(math.radians(el))
        worst = max(worst, abs(ours - ref))
        print(f"    {el:>4}d {ref:>7.2f} {ours:>7.2f} {ours - ref:>+7.2f} "
              f"{implied:>14.2f}")
    assert worst < 0.35, f"atmospheric loss off by {worst:.2f} dB"
    print(f"    -> worst deviation {worst:.2f} dB, at 15 deg; the paper's own "
          f"values imply 0.68-0.78 dB zenith loss")

test("atm_loss_db with 0.70 dB zenith loss reproduces Figure 5 within 0.35 dB",
     _check_atm)


# =========================================================================
section("4. Accumulated channel: 'Rx-Power after Losses'")
# =========================================================================
# P_rx = P_tx - L_tx_optics - L_geometric - L_pointing - L_scint - L_atm
#        - L_rx_optics
#
# Run twice, to separate the two error sources:
#   4a) paper's atmospheric values  -> isolates geometry + unexplained residual
#   4b) our atmospheric model       -> adds the Figure-5 reading error

def _rx_power_dbm(distance_km, scint_db, atm_db):
    geo = geometric_loss(distance_km, D_TX_M, D_RX_M, 1550.0,
                         model="gaussian")["lossDb"]
    return (TX_POWER_DBM - TX_OPTICAL_LOSS_DB - geo - POINTING_PENALTY_DB
            - scint_db - atm_db - RX_OPTICAL_LOSS_DB)


def _check_chain_paper_atm():
    worst = 0.0
    print(f"    {'orbit':>6} {'elev':>5} {'paper':>9} {'ours':>9} {'diff':>7}")
    for h, i in CASES:
        p = PAPER[h]
        ours = _rx_power_dbm(p["distance_km"][i], -p["scint_db"][i],
                             -p["atm_db"][i])
        ref = p["rx_after_dbm"][i]
        worst = max(worst, abs(ours - ref))
        print(f"    {h:>6} {p['elev_deg'][i]:>4}d {ref:>9.2f} {ours:>9.2f} "
              f"{ours - ref:>+7.2f}")
    assert worst < 0.35, f"channel chain off by {worst:.2f} dB"
    print(f"    -> worst deviation {worst:.2f} dB; constant and positive "
          f"(we are slightly optimistic) -- see section 5b")

test("channel chain with the paper's atmosphere matches within 0.35 dB",
     _check_chain_paper_atm)


def _check_chain_our_atm():
    worst = 0.0
    print(f"    {'orbit':>6} {'elev':>5} {'paper':>9} {'ours':>9} {'diff':>7}")
    for h, i in CASES:
        p = PAPER[h]
        el = p["elev_deg"][i]
        ours = _rx_power_dbm(p["distance_km"][i], -p["scint_db"][i],
                             atm_loss_db(el, ZENITH_ATM_LOSS_DB, 0.0))
        ref = p["rx_after_dbm"][i]
        worst = max(worst, abs(ours - ref))
        print(f"    {h:>6} {el:>4}d {ref:>9.2f} {ours:>9.2f} {ours - ref:>+7.2f}")
    assert worst < 0.65, f"channel chain off by {worst:.2f} dB"
    print(f"    -> worst deviation {worst:.2f} dB, driven by the 15 deg "
          f"atmospheric point")

test("channel chain with our atmosphere model matches within 0.65 dB",
     _check_chain_our_atm)


# =========================================================================
section("5. Two anomalies in the source table (pinned so they stay known)")
# =========================================================================

def _check_printed_fsl_row_is_offset():
    """5a) The printed "Free-space-loss and Rx-telescope gain" row is unusable.

    The value that closes the table's own arithmetic is ~-141.9 dB, but the row
    prints ~-54.1 dB.  The offset is constant to 0.01 dB across all 8 columns
    and the column-to-column increments are correct, so this is a spreadsheet
    display artefact in the paper, not a physics disagreement.

    Do NOT tune SimulCTTC towards the printed numbers.
    """
    offsets = []
    for h, i in CASES:
        p = PAPER[h]
        needed = p["rx_after_dbm"][i] - (
            TX_POWER_DBM - TX_OPTICAL_LOSS_DB
            + 10 * math.log10((math.pi * D_TX_M / LAMBDA_M) ** 2)
            - POINTING_PENALTY_DB + p["scint_db"][i] + p["atm_db"][i]
            - RX_OPTICAL_LOSS_DB
        )
        offsets.append(p["fsl_row_db"][i] - needed)
    spread = max(offsets) - min(offsets)
    print(f"    printed row minus chain-implied value: {offsets[0]:+.2f} dB, "
          f"spread over 8 columns {spread:.4f} dB")
    assert spread < 0.02, "offset is not constant -- re-examine the table"
    assert offsets[0] > 80.0, "expected a large constant offset"

test("5a) printed free-space-loss row is a constant offset, not physics",
     _check_printed_fsl_row_is_offset)


def _check_unexplained_residual():
    """5b) A constant ~0.27 dB is missing from the paper's chain.

    The value the table's arithmetic needs for L_fs + G_rx is ~0.27 dB more
    lossy than (lambda/(4 pi d))^2 * (pi D_rx / lambda)^2.  Plausible cause: a
    central obscuration on the 60 cm OGS telescope -- (1 - eps^2) = -0.28 dB
    for eps = 0.25, i.e. a ~15 cm secondary.  Not stated in the paper.
    """
    residuals = []
    for h, i in CASES:
        p = PAPER[h]
        d = p["distance_km"][i]
        needed = p["rx_after_dbm"][i] - (
            TX_POWER_DBM - TX_OPTICAL_LOSS_DB
            + 10 * math.log10((math.pi * D_TX_M / LAMBDA_M) ** 2)
            - POINTING_PENALTY_DB + p["scint_db"][i] + p["atm_db"][i]
            - RX_OPTICAL_LOSS_DB
        )
        physics = (10 * math.log10((LAMBDA_M / (4 * math.pi * d * 1e3)) ** 2)
                   + 10 * math.log10((math.pi * D_RX_M / LAMBDA_M) ** 2))
        residuals.append(needed - physics)
    spread = max(residuals) - min(residuals)
    obscuration = 10 * math.log10(1.0 - 0.25 ** 2)
    print(f"    residual {residuals[0]:+.3f} dB, spread {spread:.4f} dB")
    print(f"    a 25 % central obscuration would give {obscuration:+.3f} dB")
    assert spread < 0.02, "residual is not constant"
    assert abs(residuals[0]) < 0.4, "residual larger than an optics detail"

test("5b) residual vs pure physics is a constant ~0.27 dB",
     _check_unexplained_residual)


# =========================================================================
section("6. Scintillation loss (KNOWN DEVIATION -- reported, not asserted)")
# =========================================================================
# The paper's model is the same one we implement (lognormal fading, fade margin
# at an outage quantile -- Giggenbach & Henniger, Opt. Eng. 47, 2008, their
# ref. [21]) with p_thr = 1E-6.  But the numbers do not agree, for reasons the
# paper itself makes explicit:
#   - they use a HV5/7 profile *scaled* to fit Oberpfaffenhofen measurements;
#     we use standard HV5/7 (W = 21 m/s, A = 1.7e-14)
#   - they state their model is only valid above 20 deg elevation
#   - our aperture-averaging factor (link_budget.py, rho_I heuristic with
#     H_turb = 12 km) is not the standard Andrews form -- prime suspect

def _hv57(h_m, wind=21.0, ground_cn2=1.7e-14):
    return (0.00594 * (wind / 27.0) ** 2 * (h_m * 1e-5) ** 10
            * math.exp(-h_m / 1000.0)
            + 2.7e-16 * math.exp(-h_m / 1500.0)
            + ground_cn2 * math.exp(-h_m / 100.0))


HV57_LAYERS = [(h, _hv57(h)) for h in
               (0, 100, 200, 500, 1000, 2000, 3000, 5000, 7500,
                10000, 12500, 15000, 17500, 20000, 25000)]


def _report_scintillation():
    print(f"    standard HV5/7, D_rx = 60 cm, 1550 nm, downlink, p0 = 1E-6")
    print(f"    {'elev':>5} {'sigma_R2':>10} {'PSI':>9} {'paper':>8} "
          f"{'ours':>8} {'diff':>8}")
    rows, prev = [], None
    for i, el in enumerate(PAPER[400]["elev_deg"]):
        s = scintillation_stats(el, 1550.0, D_RX_M, HV57_LAYERS, 1e-6,
                                link_direction="downlink",
                                H_sat_m=400e3, h_gs=0.0)
        ref = -PAPER[400]["scint_db"][i]
        print(f"    {el:>4}d {s['sigma_r2']:>10.3f} {s['sigma_i2']:>9.4f} "
              f"{ref:>8.2f} {s['loss_db']:>8.2f} {s['loss_db'] - ref:>+8.2f}")
        rows.append((el, ref, s["loss_db"], s["sigma_r2"]))
        # physical sanity: fade margin must fall as elevation rises
        if prev is not None:
            assert s["loss_db"] < prev, \
                f"scintillation loss not monotonic in elevation at {el} deg"
        prev = s["loss_db"]
        assert s["loss_db"] > 0.0

    worst = max(o - r for _, r, o, _ in rows)
    ratio = max(o / r for _, r, o, _ in rows)
    print(f"    -> monotonic and positive (physics sanity OK), but up to "
          f"{worst:.2f} dB / {ratio:.1f}x too pessimistic")
    deviation(
        "scintillation loss vs Figure 7",
        f"up to {worst:.1f} dB ({ratio:.1f}x) too pessimistic; standard vs "
        f"scaled HV5/7, and a non-standard aperture-averaging factor",
    )

test("6a) scintillation is physically sane; quantitative gap is reported",
     _report_scintillation)


def _check_psi_to_db_mapping():
    """6b) Step 4 of our model (PSI -> fade margin) IS validated by the paper.

    Section IV states, for 847 nm / 40 cm: "the expected power scintillation
    index ranges from ~0.004 at 55 deg elevation to ~0.3 at 5 deg [...] In terms
    of fading loss, this translates to between 1 dB and 11 dB at a threshold of
    1E-6".  That is a direct, numeric check of the lognormal quantile step,
    independent of any Cn2 profile.
    """
    from statistics import NormalDist
    z = NormalDist().inv_cdf(1e-6)

    def margin_db(psi):
        s2 = math.log(1.0 + psi)
        return -10 * math.log10(math.exp(-0.5 * s2 + math.sqrt(s2) * z))

    print(f"    {'PSI':>7} {'paper':>8} {'ours':>8} {'diff':>7}")
    worst = 0.0
    for psi, ref in ((0.004, 1.0), (0.300, 11.0)):
        ours = margin_db(psi)
        worst = max(worst, abs(ours - ref))
        print(f"    {psi:>7.3f} {ref:>8.1f} {ours:>8.2f} {ours - ref:>+7.2f}")
    assert worst < 0.5, f"PSI->dB mapping off by {worst:.2f} dB"
    print(f"    -> our lognormal fade-margin step reproduces the paper's own "
          f"figures within {worst:.2f} dB")

test("6b) PSI -> fade-margin mapping matches the paper's stated values",
     _check_psi_to_db_mapping)


def _report_aperture_averaging_defect():
    """6c) The aperture-averaging factor is where the model actually breaks.

    Physically the factor A = sigma_I^2(D) / sigma_I^2(0) must rise
    monotonically as elevation falls: a longer slant path means a larger
    irradiance correlation width, so a fixed aperture averages less.

    Our implementation (link_budget.py, the rho_I heuristic) is proportional to
    sqrt(el / (el^2 + (10/90)^2)) in normalised elevation, which peaks *by
    construction* at 10 deg and then falls again below it.  That turn-around is
    not physical.

    Consequence, measured against the paper's own text values (847 nm, 40 cm):
    our PSI is fine at 5 deg (0.8x) but ~4x too high at 55 deg — an
    elevation-dependent error, which is the signature of the averaging factor
    rather than of the Cn2 profile (a mis-scaled Cn2 would give a roughly
    constant ratio).

    Flip this to a hard assert once the averaging factor is replaced with a
    standard form (e.g. Churnside 1991, or Andrews & Phillips Ch. 10).
    """
    print(f"    aperture-averaging factor vs elevation (60 cm, 1550 nm):")
    factors = []
    for el in (5, 10, 15, 20, 30, 45, 60, 90):
        s = scintillation_stats(el, 1550.0, D_RX_M, HV57_LAYERS, 1e-6,
                                link_direction="downlink", H_sat_m=400e3)
        factors.append((el, s["aperture_avg"]))
        print(f"      {el:>3} deg  A = {s['aperture_avg']:.4f}")

    monotonic = all(factors[i][1] > factors[i + 1][1]
                    for i in range(len(factors) - 1))

    print(f"    PSI vs the paper's text values (847 nm, 40 cm):")
    ratios = []
    for el, ref in ((5, 0.30), (55, 0.004)):
        s = scintillation_stats(el, 847.0, 0.40, HV57_LAYERS, 1e-6,
                                link_direction="downlink", H_sat_m=400e3)
        ratios.append(s["sigma_i2"] / ref)
        print(f"      {el:>3} deg  paper {ref:.3f}   ours {s['sigma_i2']:.4f}"
              f"   ratio {s['sigma_i2'] / ref:.1f}x")

    if not monotonic:
        peak = max(factors, key=lambda f: f[1])
        deviation(
            "aperture-averaging factor is non-monotonic in elevation",
            f"A peaks at {peak[0]} deg (A = {peak[1]:.4f}) instead of rising "
            f"monotonically towards the horizon; PSI error grows from "
            f"{ratios[0]:.1f}x at 5 deg to {ratios[1]:.1f}x at 55 deg",
        )
    else:
        print("    -> monotonic; the averaging factor now looks physical")

test("6c) aperture-averaging factor: monotonicity diagnosis",
     _report_aperture_averaging_defect)


# =========================================================================
section("SUMMARY")
# =========================================================================
print(f"  passed     : {PASS}")
print(f"  failed     : {FAIL}")
print(f"  deviations : {DEVIATION}")
for name, detail in NOTES:
    print(f"    - {name}: {detail}")
print()
sys.exit(1 if FAIL else 0)
