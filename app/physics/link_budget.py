# ---------------------------------------------------------------------------
# app/physics/link_budget.py
# ---------------------------------------------------------------------------
# Purpose : Sat-to-ground optical link-budget components for QKD downlink.
#
# Based on:
#   [1] QUARC: Quantum Research Cubesat — A Constellation for QC
#   [2] LEO Satellites Constellation-to-Ground QKD Links (Greek QCI)
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
from typing import List, Optional, Tuple


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


# ── D) Scintillation fading loss (turbulence) ───────────────────────────

def _rytov_variance(
    elev_deg: float,
    wavelength_nm: float,
    cn2_layers: List[Tuple[float, float]],
    h_gs: float = 0.0,
) -> float:
    """Compute Rytov variance for downlink (plane-wave approx.).

    σ_R² = 2.25 k^(7/6) sec(ζ)^(11/6) ∫ Cn²(h) (h - Hgs)^(5/6) dh

    Args:
        elev_deg: elevation in degrees.
        wavelength_nm: wavelength in nm.
        cn2_layers: list of (altitude_m, Cn²) tuples, sorted by altitude.
        h_gs: ground station altitude (m).

    Returns:
        Rytov variance (dimensionless).
    """
    if elev_deg <= 0 or len(cn2_layers) < 2:
        return 0.0

    lam = wavelength_nm * 1e-9
    k = 2.0 * math.pi / lam
    zen_rad = (90.0 - elev_deg) * math.pi / 180.0
    sec_z = 1.0 / max(math.cos(zen_rad), 1e-3)

    # Trapezoidal integration
    integral = 0.0
    for i in range(len(cn2_layers) - 1):
        h0, cn2_0 = cn2_layers[i]
        h1, cn2_1 = cn2_layers[i + 1]
        dh = h1 - h0
        if dh <= 0:
            continue
        f0 = cn2_0 * max(h0 - h_gs, 0.0) ** (5.0 / 6.0)
        f1 = cn2_1 * max(h1 - h_gs, 0.0) ** (5.0 / 6.0)
        integral += 0.5 * (f0 + f1) * dh

    sigma_r2 = 2.25 * (k ** (7.0 / 6.0)) * (sec_z ** (11.0 / 6.0)) * integral
    return sigma_r2


def scintillation_loss_db(
    elev_deg: float,
    wavelength_nm: float,
    ground_aperture_m: float,
    cn2_layers: Optional[List[Tuple[float, float]]] = None,
    p0: float = 0.01,
) -> float:
    """Scintillation fading loss at quantile *p0* (lognormal model).

    Steps:
      1) Rytov variance from Cn² profile.
      2) Point scintillation index (strong-turbulence correction).
      3) Aperture averaging.
      4) Lognormal fade margin at quantile p0.

    Args:
        elev_deg: elevation (deg).
        wavelength_nm: wavelength (nm).
        ground_aperture_m: receiver aperture diameter (m).
        cn2_layers: list of (altitude_m, Cn²) tuples.  If None → 0 dB.
        p0: outage quantile (e.g. 0.01 = 1%).

    Returns:
        Scintillation fade loss in dB (≥ 0).
    """
    if cn2_layers is None or len(cn2_layers) < 2 or elev_deg <= 0:
        return 0.0

    lam = wavelength_nm * 1e-9

    # 1) Rytov variance
    sigma_r2 = _rytov_variance(elev_deg, wavelength_nm, cn2_layers)
    if sigma_r2 < 1e-12:
        return 0.0

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

    loss = -10.0 * math.log10(I_q)
    return max(loss, 0.0)


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
