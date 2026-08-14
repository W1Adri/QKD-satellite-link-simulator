# ---------------------------------------------------------------------------
# app/physics/detector_models.py
# ---------------------------------------------------------------------------
# Purpose : Single-photon detector (SPD) non-idealities for QKD link models:
#           dead-time saturation and afterpulsing.  Pure / stateless; no I/O.
#
# Real single-photon avalanche diodes (SPADs) and superconducting nanowire
# detectors deviate from the ideal "click on every photon" picture in two
# important ways at high count rates / high background:
#
#   1. Dead time (τ_d): after each detection the detector is blind for a
#      recovery interval, saturating the achievable count rate.
#   2. Afterpulsing (p_ap): trapped carriers released after an avalanche
#      trigger spurious, time-correlated counts that raise the error rate.
#
# Functions:
#   live_fraction(incident_rate, dead_time, paralyzable)      -> float
#   saturated_rate(incident_rate, dead_time, paralyzable)     -> float
#   effective_efficiency(eta, incident_rate, dead_time, ...)  -> float
#   afterpulse_rate(primary_rate, afterpulse_prob)            -> float
#   apply_detector_effects(signal_rate, noise_rate, ...)      -> dict
#
# References:
#   [Knoll10] G. F. Knoll, "Radiation Detection and Measurement", 4th ed.,
#             Wiley (2010), §4.VII — paralyzable & non-paralyzable dead-time
#             models:  m = n/(1+nτ)  (non-par.),  m = n·e^{-nτ}  (par.).
#   [Rest13]  A. Restelli, J. C. Bienfang, A. L. Migdall, Appl. Phys. Lett.
#             102, 141104 (2013) — SPD dead-time effects in high-rate QKD.
#   [Itz07]   M. A. Itzler, X. Jiang, et al., J. Mod. Opt. 54, 283 (2007) —
#             afterpulsing in InGaAs/InP single-photon avalanche diodes.
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict


# ── Dead-time saturation ───────────────────────────────────────────────────

def live_fraction(
    incident_rate: float,
    dead_time: float,
    paralyzable: bool = False,
) -> float:
    """Fraction of time the detector is live (able to register a click).

    *incident_rate* is the would-be click rate [counts/s] in the absence of
    dead time (signal + dark + background photons that produce avalanches).
    *dead_time* is the recovery interval τ_d [s].

    Non-paralyzable model [Knoll10]:  the measured rate is m = n/(1+nτ), so
    the dead fraction is m·τ and the live fraction is

        f_live = 1 / (1 + n·τ).

    Paralyzable model: each event (even during dead time) re-triggers the
    recovery, giving m = n·e^{-nτ} and f_live = e^{-nτ}.

    Returns 1.0 when τ_d = 0 (ideal detector).
    """
    busy = max(0.0, incident_rate) * max(0.0, dead_time)
    if busy <= 0.0:
        return 1.0
    if paralyzable:
        return math.exp(-busy)
    return 1.0 / (1.0 + busy)


def saturated_rate(
    incident_rate: float,
    dead_time: float,
    paralyzable: bool = False,
) -> float:
    """Measured count rate after dead-time saturation [counts/s]."""
    return max(0.0, incident_rate) * live_fraction(
        incident_rate, dead_time, paralyzable
    )


def effective_efficiency(
    eta: float,
    incident_rate: float,
    dead_time: float,
    paralyzable: bool = False,
) -> float:
    """Detection efficiency reduced by the detector busy fraction.

    η_eff = η · f_live(incident_rate, τ_d).  Used by per-pulse QKD models
    (e.g. decoy-state) where saturation manifests as an effective drop in
    system efficiency at high incident click rates.
    """
    return max(0.0, eta) * live_fraction(incident_rate, dead_time, paralyzable)


# ── Afterpulsing ────────────────────────────────────────────────────────────

def afterpulse_rate(primary_rate: float, afterpulse_prob: float) -> float:
    """Spurious count rate from afterpulsing [counts/s].

    Each genuine ("primary") avalanche triggers a correlated afterpulse with
    probability *afterpulse_prob* (p_ap) [Itz07].  To first order the extra
    click rate is p_ap · R_primary.  Afterpulses themselves can afterpulse;
    summing the geometric series gives the closed form below, which reduces
    to p_ap · R_primary for p_ap ≪ 1.
    """
    p = max(0.0, min(afterpulse_prob, 0.999))
    if p <= 0.0:
        return 0.0
    return max(0.0, primary_rate) * p / (1.0 - p)


# ── Combined rate-domain model (BB84 / E91) ────────────────────────────────

def apply_detector_effects(
    signal_rate: float,
    noise_rate: float,
    dead_time: float = 0.0,
    afterpulse_prob: float = 0.0,
    paralyzable: bool = False,
) -> Dict[str, Any]:
    """Apply dead-time saturation and afterpulsing to detector click rates.

    Parameters
    ----------
    signal_rate : float
        Genuine signal-photon detection rate [counts/s] (ideal detector).
    noise_rate : float
        Dark-count + stray-background click rate [counts/s] (ideal detector).
    dead_time : float
        Detector dead time τ_d [s].  0 → ideal (no saturation).
    afterpulse_prob : float
        Afterpulse probability p_ap per genuine click.  0 → no afterpulsing.
    paralyzable : bool
        Use the paralyzable dead-time model instead of non-paralyzable.

    Returns
    -------
    dict with keys:
        signalRate     – saturated signal detection rate [counts/s]
        noiseRate      – saturated dark+background rate [counts/s]
        afterpulseRate – afterpulse click rate [counts/s] (error-bearing)
        liveFraction   – detector live fraction f_live ∈ (0, 1]

    Afterpulses are time-correlated but carry no key information, so callers
    should treat ``afterpulseRate`` as random (e₀ = 0.5) error counts, i.e.
    add it to the noise term feeding the QBER.

    With dead_time = 0 and afterpulse_prob = 0 this is the identity map
    (signalRate = signal_rate, noiseRate = noise_rate, afterpulseRate = 0).
    """
    incident = max(0.0, signal_rate) + max(0.0, noise_rate)
    f_live = live_fraction(incident, dead_time, paralyzable)

    sig_eff = max(0.0, signal_rate) * f_live
    noise_eff = max(0.0, noise_rate) * f_live
    ap_eff = afterpulse_rate(sig_eff + noise_eff, afterpulse_prob)

    return {
        "signalRate": sig_eff,
        "noiseRate": noise_eff,
        "afterpulseRate": ap_eff,
        "liveFraction": f_live,
    }
