# ---------------------------------------------------------------------------
# app/physics/monte_carlo.py
# ---------------------------------------------------------------------------
# Purpose : Monte Carlo channel engine (TODO-06).  A single deterministic link
#           budget gives one number; a real satellite QKD link fluctuates from
#           pulse to pulse because of atmospheric scintillation and pointing
#           jitter.  This module draws N random channel realizations, runs the
#           QKD key-rate calculator on each, and reports the resulting
#           distribution as P5/P50/P95 confidence bands plus an outage
#           probability — the statistics a paper reports for link feasibility.
#
# Physical model (per realization):
#     T_inst = T_mean · chi_scint · chi_point
#     excess_loss[dB] = -10 log10(chi_scint · chi_point)
#     channelLossdB   = mean_loss_dB + excess_loss[dB]
#
#   chi_scint — atmospheric scintillation fading factor (E[chi] = 1):
#       weak turbulence  (sigma_R^2 < 1): log-normal irradiance.
#       strong turbulence (sigma_R^2 >= 1): gamma-gamma irradiance.
#       Automatic regime switch (matches CONTEXT novelty claim #5).
#   chi_point — pointing/jitter fading factor from a Rayleigh-distributed
#       radial beam offset.  Its mean equals the deterministic Rayleigh-
#       averaged PAT fading already in link_budget.pat_fading_penalty_db.
#
# References:
#   Andrews & Phillips, "Laser Beam Propagation through Random Media", 2nd ed.
#       (2005) — Ch. 11 (log-normal), Eqs. 9.46-9.47 (gamma-gamma alpha,beta).
#   Al-Habash, Andrews & Phillips, Opt. Eng. 40, 1554 (2001) — gamma-gamma PDF.
#   Farid & Hranilovic, J. Lightwave Technol. 25, 1702 (2007) — pointing fade.
#
# Exports:
#   sample_scintillation_fading(sigma_r2, n, rng, aperture_avg) -> ndarray
#   sample_pointing_fading(jitter_rad, divergence_rad, n, rng)  -> ndarray
#   fading_to_excess_loss_db(fade)                              -> ndarray
#   monte_carlo_key_rate(base_params, protocol, ...)            -> dict
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence

import numpy as np

from app.physics.qkd import calculate_qkd


# ── Turbulence helpers (Andrews & Phillips 2005) ───────────────────────────

def _scintillation_index(sigma_r2: float) -> float:
    """Point scintillation index sigma_I^2 from Rytov variance (A&P Eq. 12.15)."""
    sr = sigma_r2 ** (6.0 / 5.0)               # sigma_R^(12/5)
    t1 = 0.49 * sigma_r2 / (1.0 + 1.11 * sr) ** (7.0 / 6.0)
    t2 = 0.51 * sigma_r2 / (1.0 + 0.69 * sr) ** (5.0 / 6.0)
    return math.exp(t1 + t2) - 1.0


def _gamma_gamma_params(sigma_r2: float) -> tuple[float, float]:
    """Gamma-gamma large/small-scale parameters (A&P Eqs. 9.46-9.47).

    alpha and beta are the effective numbers of large- and small-scale eddies.
    """
    sr = sigma_r2 ** (6.0 / 5.0)
    alpha = 1.0 / (math.exp(0.49 * sigma_r2 / (1.0 + 1.11 * sr) ** (7.0 / 6.0)) - 1.0)
    beta = 1.0 / (math.exp(0.51 * sigma_r2 / (1.0 + 0.69 * sr) ** (5.0 / 6.0)) - 1.0)
    return alpha, beta


# ── Random fading samplers ─────────────────────────────────────────────────

def sample_scintillation_fading(
    sigma_r2: float,
    n: int,
    rng: np.random.Generator,
    aperture_avg: float = 1.0,
) -> np.ndarray:
    """Draw N normalized irradiance fading factors (E[chi] = 1).

    Args:
        sigma_r2:     Rytov variance (turbulence strength); <=0 → no fading.
        n:            number of realizations.
        rng:          NumPy random generator.
        aperture_avg: aperture-averaging factor in (0, 1] applied to the
                      log-normal variance (weak-turbulence branch only).

    Regime switch: sigma_R^2 < 1 → log-normal; sigma_R^2 >= 1 → gamma-gamma.
    """
    if sigma_r2 <= 0.0 or n <= 0:
        return np.ones(max(n, 0))

    if sigma_r2 < 1.0:
        # Weak turbulence — log-normal irradiance (A&P Ch. 11).
        sigma_i2 = max(_scintillation_index(sigma_r2) * aperture_avg, 1e-15)
        sigma_ln2 = math.log(1.0 + sigma_i2)
        # mu = -sigma_ln2/2 so that E[exp(s)] = 1.
        s = rng.normal(-0.5 * sigma_ln2, math.sqrt(sigma_ln2), n)
        return np.exp(s)

    # Moderate-to-strong turbulence — gamma-gamma (A&P Eqs. 9.46-9.47).
    alpha, beta = _gamma_gamma_params(sigma_r2)
    x = rng.gamma(alpha, 1.0 / alpha, n)        # large-scale, E[x] = 1
    y = rng.gamma(beta, 1.0 / beta, n)          # small-scale, E[y] = 1
    return x * y


def sample_pointing_fading(
    jitter_rad: float,
    divergence_rad: float,
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw N pointing fading factors from Gaussian two-axis jitter.

    The radial offset (theta_x, theta_y), each N(0, jitter^2), gives an
    instantaneous Gaussian-beam coupling exp[-4(theta_x^2+theta_y^2)/omega^2]
    with omega = divergence_rad.  The ensemble mean equals the Rayleigh-
    averaged PAT fading 1/(1 + 8 jitter^2 / omega^2) used in link_budget
    (Farid & Hranilovic 2007).
    """
    if jitter_rad <= 0.0 or divergence_rad <= 0.0 or n <= 0:
        return np.ones(max(n, 0))
    tx = rng.normal(0.0, jitter_rad, n)
    ty = rng.normal(0.0, jitter_rad, n)
    return np.exp(-4.0 * (tx ** 2 + ty ** 2) / divergence_rad ** 2)


def fading_to_excess_loss_db(fade: np.ndarray) -> np.ndarray:
    """Convert a linear fading factor (0, 1+] to extra channel loss in dB (>=0
    for fade<1).  Clamped to avoid log(0)."""
    return -10.0 * np.log10(np.maximum(fade, 1e-30))


# ── Monte Carlo driver ──────────────────────────────────────────────────────

def _stats(values: np.ndarray, quantiles: Sequence[float]) -> Dict[str, float]:
    """Summary statistics (mean/std/min/max + requested percentiles)."""
    out: Dict[str, float] = {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }
    for q in quantiles:
        out[f"p{int(round(q))}"] = float(np.percentile(values, q))
    return out


def monte_carlo_key_rate(
    base_params: Dict[str, Any],
    protocol: str = "bb84",
    sigma_r2: float = 0.0,
    aperture_avg: float = 1.0,
    jitter_rad: float = 0.0,
    divergence_rad: float = 0.0,
    n_realizations: int = 1000,
    quantiles: Sequence[float] = (5.0, 50.0, 95.0),
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Monte Carlo secure-key-rate distribution over a fading channel.

    Draws *n_realizations* random channels by sampling scintillation and
    pointing fades, adds the resulting excess loss (dB) to the mean channel
    loss in *base_params['channelLossdB']*, and evaluates the QKD key rate for
    each.  Returns the SKR / QBER distributions and the outage probability
    (fraction of realizations with zero secure key).

    Args:
        base_params:    QKD params at the *mean* channel (must include
                        'channelLossdB' and the protocol's required keys).
        protocol:       QKD protocol name (see qkd.calculate_qkd).
        sigma_r2:       Rytov variance for scintillation (0 → no scintillation).
        aperture_avg:   aperture-averaging factor in (0, 1] (weak turbulence).
        jitter_rad:     RMS single-axis pointing jitter (rad); 0 → no jitter.
        divergence_rad: beam divergence half-angle omega (rad).
        n_realizations: number of Monte Carlo draws (>= 1).
        quantiles:      percentiles to report (default P5/P50/P95).
        seed:           RNG seed for reproducibility.

    Returns:
        Dict with keys: protocol, n_realizations, mean_loss_db,
        mean_excess_loss_db, skr_kbps (stats), qber_pct (stats),
        outage_probability.
    """
    n = max(int(n_realizations), 1)
    rng = np.random.default_rng(seed)

    chi_scint = sample_scintillation_fading(sigma_r2, n, rng, aperture_avg)
    chi_point = sample_pointing_fading(jitter_rad, divergence_rad, n, rng)
    excess_db = fading_to_excess_loss_db(chi_scint * chi_point)

    mean_loss_db = float(base_params["channelLossdB"])
    skr = np.empty(n, dtype=float)
    qber = np.empty(n, dtype=float)

    for i in range(n):
        params = dict(base_params)
        params["channelLossdB"] = mean_loss_db + float(excess_db[i])
        out = calculate_qkd(protocol, params)
        skr[i] = float(out.get("secureKeyRate", 0.0) or 0.0)
        qber[i] = float(out.get("qber", math.nan))

    outage = float(np.mean(skr <= 0.0))

    return {
        "protocol": protocol,
        "n_realizations": n,
        "mean_loss_db": mean_loss_db,
        "mean_excess_loss_db": float(np.mean(excess_db)),
        "skr_kbps": _stats(skr, quantiles),
        "qber_pct": _stats(qber, quantiles),
        "outage_probability": outage,
    }
