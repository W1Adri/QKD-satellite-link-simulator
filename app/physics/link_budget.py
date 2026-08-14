# ---------------------------------------------------------------------------
# app/physics/link_budget.py
# ---------------------------------------------------------------------------
# Purpose : Satellite–ground optical link-budget components for QKD
#           uplink and downlink channels.
#
# Based on:
#   [1] QUARC: Quantum Research Cubesat — A Constellation for QC
#   [2] LEO Satellites Constellation-to-Ground QKD Links (Greek QCI)
#   [3] Maharjan et al., "Atmospheric Effects on Satellite–Ground Free
#       Space Uplink and Downlink Optical Transmissions",
#       Appl. Sci. 2022, 12, 10944 — models uplink as spherical wave,
#       downlink as plane wave for Rytov variance / scintillation.
#
# Functions (all pure, no side-effects):
#   atm_loss_db(elev_deg, zenith_aod_db, zenith_abs_db)
#   pointing_loss_db(pointing_error_urad, divergence_rad)
#   scintillation_loss_db(elev_deg, wavelength_nm, ground_aperture_m,
#                         cn2_layers, p0)
#   background_cps(H_rad, fov_half_mrad, aperture_m, delta_lambda_nm,
#                  wavelength_nm)
#   total_link_loss_db(geo_db, atm_db, point_db, scint_db, fixed_db)
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple


# ── tiny erfinv (no scipy) ──────────────────────────────────────────────

def _erfinv_approx(x: float) -> float:
    """Rational approximation of erfinv valid for |x| < 1.

    Uses Winitzki-style initial guess + one Newton step on erf.
    Accuracy ≈ 1e-6 for |x| ≤ 0.99.
    """
    if x <= -1.0:
        return -6.0  # large negative
    if x >= 1.0:
        return 6.0

    sign = 1.0 if x >= 0 else -1.0
    a = abs(x)
    if a < 1e-12:
        return 0.0

    # Winitzki approximation
    ln1 = math.log(1.0 - a * a)
    c = 2.0 / (math.pi * 0.147) + 0.5 * ln1
    val = sign * math.sqrt(
        math.sqrt(c * c - ln1 / 0.147) - c
    )

    # One Newton step: erfinv(x) via erf
    for _ in range(2):
        erf_val = math.erf(val)
        deriv = 2.0 / math.sqrt(math.pi) * math.exp(-val * val)
        if abs(deriv) < 1e-30:
            break
        val -= (erf_val - x) / deriv

    return val


# ── A) Atmospheric attenuation ──────────────────────────────────────────

def atm_loss_db(
    elev_deg: float,
    zenith_aod_db: float = 0.0,
    zenith_abs_db: float = 0.0,
) -> float:
    """Atmospheric attenuation loss scaled by airmass.

    Uses airmass ≈ sec(zenith) = 1/sin(elev) with a clamp for low
    elevations.  Returns 0 when elev <= 0.

    Args:
        elev_deg: elevation angle in degrees.
        zenith_aod_db: zenith aerosol optical depth loss (dB).
        zenith_abs_db: zenith molecular absorption loss (dB).

    Returns:
        Atmospheric loss in dB (positive means loss).
    """
    if elev_deg <= 0.0:
        return 0.0
    zen_rad = (90.0 - elev_deg) * math.pi / 180.0
    cz = max(math.cos(zen_rad), 1e-3)  # clamp near-horizon
    airmass = 1.0 / cz
    return (zenith_aod_db + zenith_abs_db) * airmass


# ── C) Pointing loss (QUARC model) ──────────────────────────────────────

def pointing_loss_db(
    pointing_error_urad: float,
    divergence_rad: float,
) -> float:
    """Pointing-error loss using Gaussian beam approximation (QUARC).

    Tp = exp( -8 * alpha_p² / omega_div² )
    loss = -10 log10(Tp)

    Args:
        pointing_error_urad: 1-sigma pointing jitter (µrad).
        divergence_rad: full-angle divergence (rad), same convention
                        as geometric_loss (1.22 λ / D_t).

    Returns:
        Pointing loss in dB (≥ 0).
    """
    if pointing_error_urad <= 0 or divergence_rad <= 0:
        return 0.0
    alpha_p = pointing_error_urad * 1e-6  # µrad → rad
    ratio = alpha_p / divergence_rad
    exponent = 8.0 * ratio * ratio
    # clamp to avoid extreme dB values
    exponent = min(exponent, 50.0)
    tp = math.exp(-exponent)
    if tp <= 1e-15:
        return 150.0
    return -10.0 * math.log10(tp)


# ── C2) Pointing loss (Ntanos 2021 beta-distribution / outage model) ─────

def pointing_loss_beta_db(
    pointing_error_urad: float,
    w0_rad: float,
    p0: float = 0.01,
) -> float:
    """Pointing-error loss from the beta-distributed jitter model (outage p0).

    Ntanos et al. 2021 (Photonics 8, 544), Eq. (8)–(10) (after Kiasaleh,
    Opt. Eng. 33, 1994).  The normalized received intensity due to pointing
    jitter follows a beta PDF ``p(I) = β_p I^{β_p-1}`` on ``[0, 1]`` with

        β_p = w₀² / (4 σ_p²)                                    (Eq. 9)

    where ``w₀`` is the Gaussian half-width beam divergence (rad) and ``σ_p``
    the pointing-error standard deviation (rad).  For a target outage
    probability ``p0`` the pointing loss factor is

        L_pt = p0^{1/β_p}                                        (Eq. 10)

    Args:
        pointing_error_urad: pointing-error σ_p (µrad).
        w0_rad: Gaussian half-width divergence angle w₀ = 2λ/(πD_t) (rad).
        p0: outage probability (e.g. 0.01 = 1%).

    Returns:
        Pointing loss in dB (≥ 0).
    """
    sigma_p = pointing_error_urad * 1e-6  # µrad → rad
    if sigma_p <= 0 or w0_rad <= 0:
        return 0.0
    beta_p = (w0_rad * w0_rad) / (4.0 * sigma_p * sigma_p)
    if beta_p <= 1e-9:
        return 150.0
    p0 = min(max(p0, 1e-9), 0.999999)
    l_pt = p0 ** (1.0 / beta_p)      # L_pt ∈ (0, 1]
    return -10.0 * math.log10(max(l_pt, 1e-15))


# -- B2) Beam wander variance (uplink only) ---------------------------------

def beam_wander_variance_rad2(
    elev_deg: float,
    wavelength_nm: float,
    tx_aperture_m: float,
    r0_m: float,
    H_sat_m: float,
    link_direction: str = "downlink",
) -> float:
    """Beam wander variance sigma^2_BW in rad^2 (uplink only; returns 0 for downlink).

    For an uplink beam, atmospheric turbulence displaces the beam centroid.
    This is separate from scintillation (intensity fluctuations at a fixed point).

    Formula:
        sigma^2_BW = 0.54 * L^2 * sec(z)^(5/3) * (2*W0/r0)^(-1/3) * (lambda/(2*W0))^2

    where L = H_sat / cos(zenith), W0 = tx_aperture / 2, r0 = Fried parameter (zenith).
    The r0 value should already be scaled for the slant path by the caller if needed.

    Source: Andrews & Phillips (2005) Eq. 12.46; Vasylyev et al., PRL 117, 090501 (2016).

    Args:
        elev_deg: elevation angle (deg). Returns 0 if <= 0.
        wavelength_nm: wavelength (nm).
        tx_aperture_m: transmitter aperture diameter (m).
        r0_m: Fried parameter at zenith (m). Returns 0 if <= 0.
        H_sat_m: satellite altitude above sea level (m).
        link_direction: "uplink" or "downlink". Returns 0 for downlink.

    Returns:
        Beam wander variance in rad^2. Always >= 0.
    """
    if (link_direction or "").strip().lower() != "uplink":
        return 0.0
    if elev_deg <= 0 or r0_m <= 0 or tx_aperture_m <= 0:
        return 0.0
    lam = wavelength_nm * 1e-9
    zen_rad = (90.0 - elev_deg) * math.pi / 180.0
    sec_z = 1.0 / max(math.cos(zen_rad), 1e-3)
    W0 = tx_aperture_m / 2.0
    L = H_sat_m * sec_z  # slant path (m)
    return 0.54 * (L ** 2) * (sec_z ** (5.0 / 3.0)) * (2 * W0 / r0_m) ** (-1.0 / 3.0) * (lam / (2 * W0)) ** 2


# -- B3) PAT fading penalty (Rayleigh-averaged) -----------------------------

def pat_fading_penalty_db(
    pointing_jitter_1sigma_urad: float,
    divergence_rad: float,
) -> float:
    """Mean PAT fading penalty (dB) for Rayleigh-distributed pointing jitter.

    The instantaneous pointing error follows a Rayleigh distribution with
    1-sigma = pointing_jitter_1sigma_urad. Averaging the Gaussian beam
    transmittance T(r) = exp(-8 r^2 / omega_div^2) over this distribution:

        <T> = 1 / (1 + 8 * sigma^2 / omega_div^2)
        L_PAT = -10 log10(<T>) = 10 log10(1 + 8 * (sigma/omega_div)^2)

    The mean transmittance 1/(1+8*ratio^2) > exp(-8*ratio^2) for all ratio > 0,
    so this penalty is always LESS than pointing_loss_db() (the deterministic
    peak-jitter model). pointing_loss_db is the more conservative (pessimistic) bound.

    Uses the same full-angle divergence convention as pointing_loss_db():
    divergence_rad = 1.22 * lambda / D_t.

    Source: Bourgoin et al., Opt. Express 21, 23 (2013); Andrews & Phillips (2005) Ch. 12.

    Args:
        pointing_jitter_1sigma_urad: 1-sigma tracking jitter (urad).
        divergence_rad: full-angle beam divergence (rad).

    Returns:
        Mean fading penalty in dB (>= 0).
    """
    if pointing_jitter_1sigma_urad <= 0 or divergence_rad <= 0:
        return 0.0
    sigma_rad = pointing_jitter_1sigma_urad * 1e-6
    ratio2 = (sigma_rad / divergence_rad) ** 2
    mean_T = 1.0 / (1.0 + 8.0 * ratio2)
    return -10.0 * math.log10(max(mean_T, 1e-15))


# -- B4) Combined pointing + beam wander fading ----------------------------

def combined_pointing_fading_db(
    pat_jitter_1sigma_urad: float,
    bw_rms_urad: float,
    divergence_rad: float,
    link_direction: str = "downlink",
) -> float:
    """Combined PAT + beam wander fading penalty (dB).

    For uplink: adds beam wander variance in quadrature with PAT jitter,
    then computes the Rayleigh-averaged fading penalty.
    For downlink: beam wander is zero, so this equals pat_fading_penalty_db().

    sigma_total = sqrt(sigma_PAT^2 + sigma_BW^2)  [uplink]
    sigma_total = sigma_PAT                        [downlink]
    L = 10 log10(1 + 8 * (sigma_total / divergence)^2)

    Source: Andrews & Phillips (2005); Vasylyev et al., PRL 117, 090501 (2016).

    Args:
        pat_jitter_1sigma_urad: 1-sigma PAT jitter (urad).
        bw_rms_urad: beam wander RMS = sqrt(sigma^2_BW) converted to urad.
        divergence_rad: full-angle beam divergence (rad).
        link_direction: "uplink" or "downlink".

    Returns:
        Combined fading penalty in dB (>= 0).
    """
    sigma_pat = pat_jitter_1sigma_urad * 1e-6
    sigma_bw = bw_rms_urad * 1e-6
    if (link_direction or "").lower() == "uplink":
        sigma_total = math.sqrt(sigma_pat ** 2 + sigma_bw ** 2)
    else:
        sigma_total = sigma_pat
    if sigma_total <= 0 or divergence_rad <= 0:
        return 0.0
    ratio2 = (sigma_total / divergence_rad) ** 2
    mean_T = 1.0 / (1.0 + 8.0 * ratio2)
    return -10.0 * math.log10(max(mean_T, 1e-15))


# ── D) Scintillation fading loss (turbulence) ───────────────────────────

def _rytov_variance(
    elev_deg: float,
    wavelength_nm: float,
    cn2_layers: List[Tuple[float, float]],
    h_gs: float = 0.0,
    link_direction: str = "downlink",
    H_sat_m: float = 600_000.0,
) -> float:
    """Compute Rytov variance for downlink or uplink.

    Based on Maharjan et al., Appl. Sci. 2022, 12, 10944.

    Downlink (plane wave):
        σ_R² = 2.25 k^(7/6) sec(ζ)^(11/6) ∫ Cn²(h)(h − h₀)^(5/6) dh

    Uplink (spherical wave):
        σ_R² = 2.25 k^(7/6) sec(ζ)^(11/6) ∫ Cn²(h) [(h−h₀)(H−h)/(H−h₀)]^(5/6) dh

    Args:
        elev_deg: elevation in degrees.
        wavelength_nm: wavelength in nm.
        cn2_layers: list of (altitude_m, Cn²) tuples, sorted by altitude.
        h_gs: ground station altitude (m).
        link_direction: ``"downlink"`` (plane wave) or ``"uplink"``
            (spherical wave).
        H_sat_m: satellite altitude above sea level (m), used for
            uplink spherical-wave kernel.

    Returns:
        Rytov variance (dimensionless).
    """
    if elev_deg <= 0 or len(cn2_layers) < 2:
        return 0.0

    lam = wavelength_nm * 1e-9
    k = 2.0 * math.pi / lam
    zen_rad = (90.0 - elev_deg) * math.pi / 180.0
    sec_z = 1.0 / max(math.cos(zen_rad), 1e-3)

    is_uplink = (link_direction or "").strip().lower() == "uplink"
    H_range = max(H_sat_m - h_gs, 1.0)  # total vertical range (m)

    def _kernel(h: float) -> float:
        dh_g = max(h - h_gs, 0.0)
        if is_uplink:
            dh_s = max(H_sat_m - h, 0.0)
            return (dh_g * dh_s / H_range) ** (5.0 / 6.0)
        return dh_g ** (5.0 / 6.0)

    # Trapezoidal integration
    integral = 0.0
    for i in range(len(cn2_layers) - 1):
        h0, cn2_0 = cn2_layers[i]
        h1, cn2_1 = cn2_layers[i + 1]
        dh = h1 - h0
        if dh <= 0:
            continue
        f0 = cn2_0 * _kernel(h0)
        f1 = cn2_1 * _kernel(h1)
        integral += 0.5 * (f0 + f1) * dh

    sigma_r2 = 2.25 * (k ** (7.0 / 6.0)) * (sec_z ** (11.0 / 6.0)) * integral
    return sigma_r2


def scintillation_loss_db(
    elev_deg: float,
    wavelength_nm: float,
    ground_aperture_m: float,
    cn2_layers: Optional[List[Tuple[float, float]]] = None,
    p0: float = 0.01,
    link_direction: str = "downlink",
    H_sat_m: float = 600_000.0,
    h_gs: float = 0.0,
) -> float:
    """Scintillation fading loss at quantile *p0* (lognormal model).

    Steps:
      1) Rytov variance from Cn² profile (plane wave for downlink,
         spherical wave for uplink).
      2) Point scintillation index (strong-turbulence correction).
      3) Aperture averaging.
      4) Lognormal fade margin at quantile p0.

    Args:
        elev_deg: elevation (deg).
        wavelength_nm: wavelength (nm).
        ground_aperture_m: receiver aperture diameter (m).
        cn2_layers: list of (altitude_m, Cn²) tuples.  If None → 0 dB.
        p0: outage quantile (e.g. 0.01 = 1%).
        link_direction: ``"downlink"`` or ``"uplink"``.
        H_sat_m: satellite altitude above sea level (m).
        h_gs: ground station altitude above sea level (m).

    Returns:
        Scintillation fade loss in dB (≥ 0).
    """
    return scintillation_stats(
        elev_deg, wavelength_nm, ground_aperture_m, cn2_layers, p0,
        link_direction=link_direction, H_sat_m=H_sat_m, h_gs=h_gs,
    )["loss_db"]


def scintillation_stats(
    elev_deg: float,
    wavelength_nm: float,
    ground_aperture_m: float,
    cn2_layers: Optional[List[Tuple[float, float]]] = None,
    p0: float = 0.01,
    link_direction: str = "downlink",
    H_sat_m: float = 600_000.0,
    h_gs: float = 0.0,
) -> Dict[str, float]:
    """Scintillation fade loss *and* the intermediate turbulence statistics.

    :func:`scintillation_loss_db` returns only step 4; a Monte Carlo channel
    needs steps 1–3 as well, because it must DRAW from the same irradiance
    distribution the deterministic fade margin is a quantile of.  Both live
    here so the stochastic and deterministic paths cannot drift apart — the
    aperture-averaging factor in particular is easy to reimplement slightly
    differently, and then the MC median stops matching the p0 margin.

    Returns:
        Dict with ``sigma_r2`` (Rytov variance), ``sigma_i2_point`` (point
        scintillation index), ``aperture_avg`` (averaging factor in (0,1]),
        ``sigma_i2`` (aperture-averaged index) and ``loss_db`` (fade margin at
        quantile *p0*, ≥ 0).  All zero / unity when there is no turbulence.
    """
    null = {"sigma_r2": 0.0, "sigma_i2_point": 0.0, "aperture_avg": 1.0,
            "sigma_i2": 0.0, "loss_db": 0.0}
    if cn2_layers is None or len(cn2_layers) < 2 or elev_deg <= 0:
        return null

    lam = wavelength_nm * 1e-9

    # 1) Rytov variance
    sigma_r2 = _rytov_variance(
        elev_deg, wavelength_nm, cn2_layers,
        h_gs=h_gs,
        link_direction=link_direction, H_sat_m=H_sat_m,
    )
    if sigma_r2 < 1e-12:
        return null

    # 2) Point scintillation index (strong-turb correction, Andrews)
    sr12_5 = sigma_r2 ** (6.0 / 5.0)  # sigma_R^(12/5)
    term1 = 0.49 * sigma_r2 / (1.0 + 1.11 * sr12_5) ** (7.0 / 6.0)
    term2 = 0.51 * sigma_r2 / (1.0 + 0.69 * sr12_5) ** (5.0 / 6.0)
    sigma_I2_point = math.exp(term1 + term2) - 1.0

    # 3) Aperture averaging
    H_turb = 12000.0  # effective turbulence height (m)
    el_norm = max(elev_deg, 1.0) / 90.0
    rho_denom = el_norm ** 2 + (10.0 / 90.0) ** 2
    rho_I = 1.5 * math.sqrt((lam / (2.0 * math.pi)) * (H_turb * el_norm) / max(rho_denom, 1e-12))
    rho_I = max(rho_I, 1e-6)

    D_r = ground_aperture_m
    aa = (1.0 + 1.062 * (D_r / (2.0 * rho_I)) ** 2) ** (-7.0 / 6.0)
    sigma_I2 = aa * sigma_I2_point
    sigma_I2 = max(sigma_I2, 1e-15)

    # 4) Lognormal fade margin at quantile p0
    sigma_ln2 = math.log(1.0 + sigma_I2)
    mu_ln = -0.5 * sigma_ln2
    sigma_ln = math.sqrt(sigma_ln2)
    z = _erfinv_approx(2.0 * p0 - 1.0)
    ln_Iq = mu_ln + math.sqrt(2.0) * sigma_ln * z
    I_q = math.exp(ln_Iq)
    I_q = max(I_q, 1e-15)  # clamp

    return {
        "sigma_r2": sigma_r2,
        "sigma_i2_point": sigma_I2_point,
        "aperture_avg": aa,
        "sigma_i2": sigma_I2,
        "loss_db": max(-10.0 * math.log10(I_q), 0.0),
    }


# ── E) Background noise ─────────────────────────────────────────────────

def background_noise_cps(
    H_rad_W_m2_sr_um: float,
    fov_half_mrad: float,
    aperture_m: float,
    delta_lambda_nm: float,
    wavelength_nm: float,
) -> float:
    """Background photon count rate from sky radiance.

    P_back = H_rad · Ω · A_r · Δλ
    cps    = P_back / (hc/λ)

    Args:
        H_rad_W_m2_sr_um: sky spectral radiance (W / m² / sr / µm).
        fov_half_mrad: receiver half-angle field of view (mrad).
        aperture_m: receiver aperture diameter (m).
        delta_lambda_nm: optical filter bandwidth (nm).
        wavelength_nm: centre wavelength (nm).

    Returns:
        Background count rate in counts per second.
    """
    if (H_rad_W_m2_sr_um <= 0 or fov_half_mrad <= 0 or
            aperture_m <= 0 or delta_lambda_nm <= 0 or wavelength_nm <= 0):
        return 0.0

    fov_half_rad = fov_half_mrad * 1e-3  # mrad → rad
    omega = math.pi * fov_half_rad ** 2  # solid angle (sr)
    a_r = math.pi * (aperture_m / 2.0) ** 2  # receiver area (m²)
    delta_lam_um = delta_lambda_nm * 1e-3  # nm → µm

    p_back = H_rad_W_m2_sr_um * omega * a_r * delta_lam_um  # watts

    # photon energy
    h = 6.62607015e-34
    c = 2.99792458e8
    lam_m = wavelength_nm * 1e-9
    e_photon = h * c / lam_m

    return p_back / e_photon


# ── E2) Temporal gating (daytime QKD) ───────────────────────────────────

def temporal_gating_duty_cycle(
    gate_time_s: float,
    pulse_rate_hz: float,
) -> float:
    """Duty cycle of a time-gated single-photon receiver.

    A gated receiver only accepts photons within a short detection window of
    width Δt_gate centred on each expected pulse arrival.  Over one pulse
    period T = 1/f_rep the gate is open a fraction

        d = Δt_gate · f_rep      (clamped to [0, 1])

    so a continuous (Poissonian) background of rate R_bg is suppressed by the
    same factor.  This is the temporal-filtering pillar of daytime free-space
    QKD, alongside spatial (FOV) and spectral (Δλ) filtering.

    Ref: Liao et al., Nature Photonics 11, 509 (2017), Methods;
         Er-long Miao et al., New J. Phys. 7, 215 (2005).

    Args:
        gate_time_s:   detection gate width Δt_gate [s].
        pulse_rate_hz: pulse repetition / source rate f_rep [Hz].

    Returns:
        Dimensionless duty cycle in [0, 1].  Returns 1.0 (no suppression)
        when either input is non-positive (ungated receiver).
    """
    if gate_time_s <= 0.0 or pulse_rate_hz <= 0.0:
        return 1.0
    return min(1.0, gate_time_s * pulse_rate_hz)


def gated_background_cps(
    bg_cps: float,
    gate_time_s: float,
    pulse_rate_hz: float,
) -> float:
    """Effective continuous background rate seen through a time gate.

        R_bg,gated = R_bg · (Δt_gate · f_rep)

    The gated rate keeps the same per-pulse interpretation used downstream
    (BB84 rate-domain noise and decoy per-pulse Y₀): a narrower gate scales
    the background photons admitted per pulse linearly with Δt_gate.

    Ref: Liao et al., Nature Photonics 11, 509 (2017).

    Args:
        bg_cps:        ungated background photon rate at receiver input [cps].
        gate_time_s:   detection gate width Δt_gate [s].
        pulse_rate_hz: pulse repetition rate f_rep [Hz].

    Returns:
        Gated background count rate [cps] (≤ bg_cps).
    """
    if bg_cps <= 0.0:
        return 0.0
    return bg_cps * temporal_gating_duty_cycle(gate_time_s, pulse_rate_hz)


# ── F) Total link loss ──────────────────────────────────────────────────

def total_link_loss_db(
    geo_db: float,
    atm_db: float,
    point_db: float,
    scint_db: float,
    fixed_db: float,
) -> float:
    """Sum all link-budget loss components (dB).

    Returns:
        Total loss in dB (≥ 0).
    """
    return max(geo_db + atm_db + point_db + scint_db + fixed_db, 0.0)


def coupling_from_loss(loss_db: float) -> float:
    """Convert total loss (dB) to linear coupling in (0, 1]."""
    return min(1.0, 10.0 ** (-loss_db / 10.0))


# ── G) Sun-core angle and eclipse detection ─────────────────────────────

_EARTH_RADIUS_M = 6371000.0   # mean Earth radius (m)
_SUN_DISTANCE_M = 1.496e11    # mean Earth–Sun distance (m)
_SUN_RADIUS_M = 6.957e8       # solar radius (m)


def sun_core_angle_deg(
    sat_eci: List[float],
    station_eci: List[float],
    sun_dir_eci: List[float],
) -> float:
    """Angular separation between the satellite LOS and the Sun, from the station.

    Args:
        sat_eci: satellite position in ECI (km).
        station_eci: ground station position in ECI (km).
        sun_dir_eci: Earth→Sun *unit* vector in ECI.

    Returns:
        Angle in degrees [0, 180].
    """
    # LOS vector from station to satellite (unnormalised)
    dx = sat_eci[0] - station_eci[0]
    dy = sat_eci[1] - station_eci[1]
    dz = sat_eci[2] - station_eci[2]
    norm_los = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm_los < 1e-9:
        return 0.0

    # Normalise
    lx, ly, lz = dx / norm_los, dy / norm_los, dz / norm_los

    # Sun direction is already a unit vector
    cos_angle = lx * sun_dir_eci[0] + ly * sun_dir_eci[1] + lz * sun_dir_eci[2]
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def is_eclipsed(sat_eci_km: List[float], sun_dir_eci: List[float]) -> bool:
    """Determine if the satellite is in Earth's cylindrical shadow.

    Uses a simple cylindrical shadow model: the satellite is eclipsed if
    it lies behind the Earth (relative to the Sun) and within the Earth's
    geometric cross-section.

    Args:
        sat_eci_km: satellite position in ECI (km).
        sun_dir_eci: Earth→Sun *unit* vector in ECI.

    Returns:
        True if the satellite is in shadow.
    """
    R_E = _EARTH_RADIUS_M / 1000.0  # km

    # Project satellite position onto sun direction
    dot = (sat_eci_km[0] * sun_dir_eci[0] +
           sat_eci_km[1] * sun_dir_eci[1] +
           sat_eci_km[2] * sun_dir_eci[2])

    # Satellite must be on the anti-sun side (dot < 0)
    if dot >= 0:
        return False

    # Perpendicular distance from the Earth-Sun axis
    px = sat_eci_km[0] - dot * sun_dir_eci[0]
    py = sat_eci_km[1] - dot * sun_dir_eci[1]
    pz = sat_eci_km[2] - dot * sun_dir_eci[2]
    perp_dist = math.sqrt(px * px + py * py + pz * pz)

    return perp_dist < R_E


# ── H) Received power and link margin ──────────────────────────────────

def received_power_dbm(
    tx_power_dbm: float,
    total_loss_db: float,
) -> float:
    """Received optical power.

    Args:
        tx_power_dbm: transmitter power (dBm).
        total_loss_db: total channel loss (dB, positive).

    Returns:
        Received power in dBm.
    """
    return tx_power_dbm - total_loss_db


def link_margin_db(
    rx_power_dbm: float,
    sensitivity_dbm: float,
) -> float:
    """Link margin above receiver sensitivity.

    Args:
        rx_power_dbm: received power (dBm).
        sensitivity_dbm: minimum detectable power (dBm).

    Returns:
        Margin in dB.  Positive means link is viable.
    """
    return rx_power_dbm - sensitivity_dbm


# ── I) Shot noise ───────────────────────────────────────────────────────

_H_PLANCK = 6.62607015e-34  # J·s
_C_LIGHT = 2.99792458e8     # m/s


def signal_shot_noise_cps(
    photon_rate: float,
    channel_loss_db: float,
    detector_efficiency: float,
) -> float:
    """Signal-induced shot noise contribution (counts per second).

    This is simply the detected signal rate — shot noise variance equals
    the mean count rate for Poisson statistics.

    Args:
        photon_rate: source photon rate (cps).
        channel_loss_db: total channel loss (dB, positive).
        detector_efficiency: detector quantum efficiency (0–1).

    Returns:
        Detected signal photon rate (cps).
    """
    eta = 10.0 ** (-channel_loss_db / 10.0)
    return photon_rate * eta * detector_efficiency


def stray_light_noise_cps(
    background_cps: float,
    detector_efficiency: float,
) -> float:
    """Stray-light (background) shot noise at the detector.

    Args:
        background_cps: background photon rate at receiver input (cps).
        detector_efficiency: detector quantum efficiency (0–1).

    Returns:
        Detected stray-light count rate (cps).
    """
    return background_cps * detector_efficiency


def total_noise_variance_cps(
    dark_count_rate: float,
    signal_shot_cps: float,
    stray_cps: float,
) -> float:
    """Total noise variance in counts per second (Poisson model).

    For a Poisson process the variance equals the mean rate.
    Total noise = dark counts + detected signal shot noise + stray light.

    Args:
        dark_count_rate: detector dark counts (cps).
        signal_shot_cps: detected signal rate (cps).
        stray_cps: detected stray-light rate (cps).

    Returns:
        Total noise variance (cps).
    """
    return dark_count_rate + signal_shot_cps + stray_cps
