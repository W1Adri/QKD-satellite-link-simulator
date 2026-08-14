# ---------------------------------------------------------------------------
# app/physics/qkd.py
# ---------------------------------------------------------------------------
# Purpose : Quantum Key Distribution secure-key-rate calculators for the
#           three supported protocols: BB84, E91 (entanglement) and CV-QKD.
#
# Functions:
#   calculate_bb84(params)         – WCP BB84 key rate (simple shot-noise model)
#   calculate_bb84_decoy(params)   – two-intensity decoy-state BB84 (GLLP formula)
#   calculate_e91(params)          – entanglement-based E91 key rate
#   calculate_cvqkd(params)        – continuous-variable Gaussian modulation
#   calculate_qkd(protocol, params)– dispatcher
#   finite_key_fraction(n, eps)    – finite-key correction factor helper
#
# References (QKD security):
#   [BB84]   Bennett & Brassard, Proc. IEEE CSSP, 1984.
#   [SP2000] Shor & Preskill, PRL 85, 441 (2000).
#   [LMC05]  Lo, Ma & Chen, PRL 94, 230504 (2005) – decoy-state QKD.
#   [Ma05]   Ma et al., PRA 72, 012326 (2005) – practical decoy state.
#   [RMP09]  Scarani et al., Rev. Mod. Phys. 81, 1301 (2009) – QKD security.
#   [Tom12]  Tomamichel et al., Nature Commun. 3, 634 (2012) – finite-key.
#   [Lim14]  Lim et al., PRA 89, 022307 (2014) – finite-key decoy-state.
#
# Inputs (common): photonRate, channelLossdB, detectorEfficiency,
#                  darkCountRate.
# Outputs: {qber, rawKeyRate, secureKeyRate, channelTransmittance, protocol}
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from app.physics.detector_models import apply_detector_effects, effective_efficiency
# Untrusted-relay protocols (MDI-QKD, TF-QKD) live in their own module to keep
# qkd.py focused on point-to-point protocols.  Re-exported for the dispatcher.
from app.physics.mdi_tf_qkd import (  # noqa: F401
    calculate_mdiqkd,
    calculate_tfqkd,
)
# Composable finite-key bounds (Tomamichel et al. 2012 [Tom12]).  Re-exported
# here so callers can keep importing `finite_key_fraction` from `qkd`.
from app.physics.finite_key import (  # noqa: F401
    finite_key_fraction,
    finite_key_length_bb84,
)


def _h(x: float) -> float:
    """Binary Shannon entropy."""
    if x <= 0 or x >= 1:
        return 0.0
    return -x * math.log2(x) - (1 - x) * math.log2(1 - x)


# ── BB84 ─────────────────────────────────────────────────────────────────

_QBER_THRESHOLD_BB84 = 0.11
_INFO_RECON_EFF = 1.16  # practical error-correction overhead


def calculate_bb84(params: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate BB84 secure key rate.

    Required keys in *params*:
        photonRate, channelLossdB, detectorEfficiency, darkCountRate.
    Optional:
        backgroundCps – stray-light background photon rate at receiver input.
    """
    try:
        photon_rate = float(params["photonRate"])
        loss_db = float(params["channelLossdB"])
        det_eff = float(params["detectorEfficiency"])
        dark_rate = float(params["darkCountRate"])
        bg_cps = float(params.get("backgroundCps", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid BB84 input: {exc}"}

    eta = 10.0 ** (-loss_db / 10.0)          # channel transmittance
    mu = 0.5                                  # mean photon number (WCP)
    det_rate = photon_rate * eta * det_eff * math.exp(-mu)

    # Noise model: dark counts + background counts at detector input
    # (dark + background counts are random, half contribute to bit errors)
    stray_shot = bg_cps * det_eff
    total_noise = dark_rate + stray_shot      # total noise click rate (cps)

    # Detector non-idealities: dead-time saturation + afterpulsing.
    # Defaults (deadTime=0, afterpulseProb=0) reproduce the ideal detector.
    dead_time = float(params.get("deadTime", 0.0))
    afterpulse = float(params.get("afterpulseProb", 0.0))
    paralyzable = bool(params.get("paralyzable", False))
    det = apply_detector_effects(
        det_rate, total_noise, dead_time, afterpulse, paralyzable
    )
    det_rate = det["signalRate"]
    afterpulse_cps = det["afterpulseRate"]
    live_fraction = det["liveFraction"]
    # Afterpulses are random (e₀ = 0.5) → fold into the noise term.
    total_noise = det["noiseRate"] + afterpulse_cps

    # QBER: half of noise clicks are errors; total detection rate is the full
    # denominator (signal + ALL noise clicks).  Using only noise/2 in the
    # denominator was a bug – it underestimates the denominator and therefore
    # overestimates QBER (conservative but inconsistent with standard BB84
    # analysis where QBER = error_rate / total_detection_rate).
    error_rate = total_noise / 2.0
    total_det = det_rate + total_noise
    qber = error_rate / total_det if total_det > 0 else 1.0

    sift = 0.5
    sifted = total_det * sift                 # sifted raw bit rate (cps)
    pa_cost = _h(qber) * sifted
    ec_leak = _INFO_RECON_EFF * _h(qber) * sifted
    skr = max(0.0, sifted - pa_cost - ec_leak)
    if qber > _QBER_THRESHOLD_BB84:
        skr = 0.0

    # Optional composable finite-key correction (Tomamichel et al. 2012).
    # Off by default (finite_key_n absent) so existing runs are unchanged.
    finite_key_n = params.get("finite_key_n")
    fk_fraction = 1.0
    if finite_key_n is not None and skr > 0.0:
        eps = float(params.get("epsilon_sec", 1e-10))
        fk_fraction = finite_key_fraction(float(finite_key_n), eps, qber)
        skr *= fk_fraction

    return {
        "qber": qber * 100,
        "rawKeyRate": sifted / 1000,
        "secureKeyRate": skr / 1000,
        "channelTransmittance": eta,
        "detectionRate": det_rate,
        "siftedKeyRate": sifted,
        "strayNoiseCps": stray_shot,
        "totalNoiseCps": total_noise,
        "afterpulseCps": afterpulse_cps,
        "liveFraction": live_fraction,
        "finiteKeyFraction": fk_fraction,
        "protocol": "BB84",
    }


# ── E91 ──────────────────────────────────────────────────────────────────

_QBER_THRESHOLD_E91 = 0.15


def calculate_e91(params: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate E91 (entanglement-based) secure key rate."""
    try:
        pair_rate = float(params["photonRate"]) / 2.0
        loss_db = float(params["channelLossdB"])
        det_eff = float(params["detectorEfficiency"])
        dark_rate = float(params["darkCountRate"])
        bg_cps = float(params.get("backgroundCps", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid E91 input: {exc}"}

    eta = 10.0 ** (-loss_db / 10.0)
    coinc = pair_rate * (eta * det_eff) ** 2

    # Noise: dark counts + stray-light shot noise for both detectors
    stray_shot = bg_cps * det_eff
    total_noise_per_det = dark_rate + stray_shot
    acc = total_noise_per_det ** 2 / max(pair_rate, 1)
    qber = acc / (coinc + acc) if (coinc + acc) > 0 else 1.0

    skr = max(0.0, coinc * (1 - 2 * _h(qber)))
    if qber > _QBER_THRESHOLD_E91:
        skr = 0.0

    return {
        "qber": qber * 100,
        "rawKeyRate": coinc / 1000,
        # Sifted block rate [counts/s].  This model's key rate is
        # coinc·(1 − 2h(Q)) with no explicit basis-sifting factor, so the block
        # that enters EC+PA is the coincidence rate itself; using coinc/2 here
        # would contradict the rate formula above.
        "siftedKeyRate": coinc,
        "secureKeyRate": skr / 1000,
        "channelTransmittance": eta,
        "detectionRate": coinc,
        "strayNoiseCps": stray_shot,
        "totalNoiseCps": total_noise_per_det,
        "protocol": "E91",
    }


# ── CV-QKD ───────────────────────────────────────────────────────────────

def calculate_cvqkd(params: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate continuous-variable QKD performance."""
    try:
        loss_db = float(params["channelLossdB"])
        det_eff = float(params["detectorEfficiency"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid CV-QKD input: {exc}"}

    mod_var = 10.0
    e_noise = 0.01
    eta = 10.0 ** (-loss_db / 10.0)
    total_eta = eta * det_eff
    snr = total_eta * mod_var / (1 + e_noise)
    excess = e_noise / max(total_eta, 1e-12)
    sym_rate = 100e6
    skr = max(0.0, sym_rate * (
        math.log2(1 + snr) - math.log2(1 + excess)
    ))
    eff_qber = excess / (snr + excess) if (snr + excess) > 0 else 1.0

    return {
        "qber": eff_qber * 100,
        "rawKeyRate": sym_rate / 1000,
        "secureKeyRate": skr / 1000,
        "channelTransmittance": eta,
        "snr": snr,
        "protocol": "CV-QKD",
    }

# ── BB84 decoy-state ─────────────────────────────────────────────────────

def calculate_bb84_decoy(params: Dict[str, Any]) -> Dict[str, Any]:
    """Two-intensity decoy-state BB84 asymptotic secure key rate.

    Implements the decoy-state analysis of Ma et al., PRA 72, 012326 (2005)
    [Ma05] using signal (μ_s) and weak-decoy (μ_d) intensities plus an
    implicit vacuum state (μ = 0).  The key rate follows the GLLP /
    Shor-Preskill bound as laid out in Scarani et al. 2009 [RMP09] Eq. (57):

        R ≥ q { μ_s e^{−μ_s} Y₁^low [1 − h(e₁^up)] − Q_s f_EC h(E_s) }

    where the single-photon yield lower bound Y₁^low and phase-error upper
    bound e₁^up are extracted from the signal and decoy gain measurements
    ([Ma05] Appendix B, Eq. B8):

        Y₁^low = (μ_s / (μ_d (μ_s − μ_d))) ×
                 { Q_d e^{μ_d} − Y₀ − (μ_d/μ_s)² (Q_s e^{μ_s} − Y₀) }

        e₁^up  = (E_d Q_d e^{μ_d} − e₀ Y₀) / (μ_d Y₁^low)

    Total gains Q_s, Q_d use the exact threshold-detector Poisson model
    (valid for arbitrary μ · η; no truncation required):

        Q_μ = 1 − (1 − Y₀) exp(−μ η_total)

    Required keys in *params*:
        photonRate          – laser pulse rate [pulses / s]
        channelLossdB       – total channel loss [dB, positive]
        detectorEfficiency  – detector quantum efficiency [0, 1]
        darkCountRate       – dark count rate [counts / s]

    Optional keys (with defaults):
        backgroundCps       – background photon rate at detector input (0)
        mu_signal           – signal mean photon number (0.6)
        mu_decoy            – decoy mean photon number (0.1)
        e_optical           – optical alignment QBER, e.g. 0.02 for 2 % (0.02)
        finite_key_n        – sifted bits per pass for finite-key correction;
                              if provided, the returned secureKeyRate is
                              scaled by finite_key_fraction(finite_key_n).
        epsilon_sec         – composable security parameter for finite-key (1e-10)
    """
    try:
        photon_rate = float(params["photonRate"])
        loss_db = float(params["channelLossdB"])
        det_eff = float(params["detectorEfficiency"])
        dark_rate = float(params["darkCountRate"])
        bg_cps = float(params.get("backgroundCps", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid BB84-decoy input: {exc}"}

    mu_s = float(params.get("mu_signal", 0.6))   # signal intensity
    mu_d = float(params.get("mu_decoy", 0.1))    # decoy intensity
    e_opt = float(params.get("e_optical", 0.02)) # optical alignment QBER

    # Degenerate-intensity guard
    if mu_s <= 0 or mu_d <= 0 or mu_s <= mu_d:
        return {"error": "mu_signal must be > mu_decoy > 0"}

    pulse_rate = photon_rate   # pulse repetition rate [Hz]

    # ── Channel model ────────────────────────────────────────────────────
    eta_ch = 10.0 ** (-loss_db / 10.0)       # channel transmittance
    eta_total = eta_ch * det_eff              # total system efficiency

    # Vacuum (dark + background) probability per pulse: Y₀
    # Default: noise counts spread over the full pulse period (1/f_rep).
    # Paper-mode (Ntanos 2021, Eq. A6): Y₀ = P_dc + P_noise with both scaled by
    # the detector gate window t_gate, i.e. (dark + bg·η_det)·t_gate.
    gate_time_s = float(params.get("gate_time_s", 0.0) or 0.0)
    paper_noise = bool(params.get("paper_noise", False))
    if paper_noise and gate_time_s > 0.0:
        noise_per_pulse = (dark_rate + bg_cps * det_eff) * gate_time_s
    else:
        noise_per_pulse = (dark_rate + bg_cps * det_eff) / max(pulse_rate, 1.0)
    Y_0 = min(noise_per_pulse, 0.5)

    # ── Detector non-idealities: dead-time + afterpulsing ────────────────
    # Defaults (deadTime=0, afterpulseProb=0) reproduce the ideal detector.
    # Dead time saturates the detector → effective system efficiency drops by
    # the live fraction evaluated at the nominal signal click rate.  Afterpulses
    # add error-bearing random clicks → raise the vacuum yield Y₀ (e₀ = 0.5).
    dead_time = float(params.get("deadTime", 0.0))
    afterpulse = float(params.get("afterpulseProb", 0.0))
    paralyzable = bool(params.get("paralyzable", False))
    live_fraction = 1.0
    if dead_time > 0.0:
        Q_s_nom = 1.0 - (1.0 - Y_0) * math.exp(-mu_s * eta_total)
        click_rate = Q_s_nom * pulse_rate                 # signal clicks/s
        eta_total = effective_efficiency(
            eta_total, click_rate, dead_time, paralyzable
        )
        live_fraction = eta_total / (eta_ch * det_eff) if (eta_ch * det_eff) > 0 else 1.0
    if afterpulse > 0.0:
        Q_s_nom = 1.0 - (1.0 - Y_0) * math.exp(-mu_s * eta_total)
        Y_0 = min(Y_0 + afterpulse * Q_s_nom, 0.5)         # afterpulse → vacuum

    # ── Total gains (exact threshold-detector model) ─────────────────────
    # Q_μ = 1 − (1 − Y₀) exp(−μ η_total)   [Ma05, eq. preceding B1]
    Q_s = 1.0 - (1.0 - Y_0) * math.exp(-mu_s * eta_total)
    Q_d = 1.0 - (1.0 - Y_0) * math.exp(-mu_d * eta_total)

    # ── QBERs ────────────────────────────────────────────────────────────
    # Error clicks originate from: (1) vacuum/dark counts (random, e₀ = 0.5)
    # and (2) optical misalignment (rate e_opt per correctly detected photon).
    # E_μ Q_μ = e₀ Y₀ exp(−μ) + e_opt (Q_μ − Y₀ exp(−μ))
    e_0 = 0.5
    vac_s = Y_0 * math.exp(-mu_s)
    vac_d = Y_0 * math.exp(-mu_d)
    E_s = (e_0 * vac_s + e_opt * (Q_s - vac_s)) / Q_s if Q_s > 1e-15 else 0.5
    E_d = (e_0 * vac_d + e_opt * (Q_d - vac_d)) / Q_d if Q_d > 1e-15 else 0.5
    E_s = max(0.0, min(E_s, 0.5))
    E_d = max(0.0, min(E_d, 0.5))

    # ── Single-photon yield lower bound (Ma et al. 2005, Appendix B, Eq. B8)
    # Y₁^low = (μ_s / (μ_d (μ_s − μ_d))) ×
    #          { Q_d e^{μ_d} − Y₀ − (μ_d/μ_s)² (Q_s e^{μ_s} − Y₀) }
    ratio_sq = (mu_d / mu_s) ** 2
    bracket = (
        Q_d * math.exp(mu_d)
        - Y_0
        - ratio_sq * (Q_s * math.exp(mu_s) - Y_0)
    )
    Y_1_low = max(0.0, mu_s / (mu_d * (mu_s - mu_d)) * bracket)

    # ── Phase error upper bound (Ma et al. 2005, Eq. B9) ────────────────
    # e₁^up = (E_d Q_d e^{μ_d} − e₀ Y₀) / (μ_d Y₁^low)
    if Y_1_low > 1e-20:
        e_1_up = (E_d * Q_d * math.exp(mu_d) - e_0 * Y_0) / (mu_d * Y_1_low)
        e_1_up = max(0.0, min(e_1_up, 0.5))
    else:
        e_1_up = 0.5   # worst case: no key

    # ── Key rate (GLLP / Shor-Preskill, Scarani et al. 2009, Eq. 57) ────
    # R ≥ q { μ_s e^{−μ_s} Y₁^low [1 − h(e₁^up)] − Q_s f_EC h(E_s) }
    # q = protocol efficiency. Default 0.5 (BB84 random-basis sifting). Ntanos
    # et al. 2021 (Photonics 8, 544) use q = 2/5 (Eq. A1); pass q via params.
    q = float(params.get("q", 0.5))
    f_ec = float(params.get("f_ec", _INFO_RECON_EFF))  # EC efficiency f(e); paper 1.22
    Q_1_s = mu_s * math.exp(-mu_s) * Y_1_low   # single-photon gain (signal)
    pa_term = Q_1_s * (1.0 - _h(e_1_up))
    ec_term = f_ec * Q_s * _h(E_s)
    skr_per_pulse = max(0.0, q * (pa_term - ec_term))
    if E_s > _QBER_THRESHOLD_BB84:
        skr_per_pulse = 0.0

    # ── Finite-key correction (optional) ─────────────────────────────────
    # Full composable finite-key treatment (Tomamichel et al. 2012, Eq. 2):
    # scale the asymptotic decoy rate by ℓ_finite/ℓ_∞ evaluated at the operating
    # signal QBER E_s and the per-pass sifted count.  k (parameter-estimation
    # bits) defaults to n inside finite_key_fraction (symmetric bases).
    finite_key_n = params.get("finite_key_n")
    fk_fraction = 1.0
    if finite_key_n is not None:
        eps = float(params.get("epsilon_sec", 1e-10))
        n_sifted = float(finite_key_n)
        fk_fraction = finite_key_fraction(n_sifted, eps, E_s)

    skr_bps = skr_per_pulse * pulse_rate * fk_fraction
    raw_bps = Q_s * pulse_rate * q

    return {
        "qber": E_s * 100,                       # QBER [%]
        "rawKeyRate": raw_bps / 1e3,             # kbit/s
        # Sifted block rate [counts/s] — the bits that enter EC+PA, i.e. the
        # signal-state detections surviving basis sifting: Q_s · f_rep · q.
        # Same quantity as rawKeyRate, in counts/s rather than kbit/s, matching
        # the convention established by calculate_bb84.  This is the rate whose
        # pass integral is the finite-key block size n.
        "siftedKeyRate": raw_bps,
        "secureKeyRate": skr_bps / 1e3,          # kbit/s
        "secureKeyRatePerPulse": skr_per_pulse * fk_fraction,  # bits/pulse (SKR/f_rep)
        "channelTransmittance": eta_ch,
        "detectionRate": Q_s * pulse_rate,       # events/s
        "singlePhotonYield": Y_1_low,            # Y₁^low
        "singlePhotonGain": Q_1_s,               # Q₁_s (signal)
        "singlePhotonPhaseError": e_1_up * 100,  # e₁^up [%]
        "signalGain": Q_s,
        "decoyGain": Q_d,
        # Per-intensity channel statistics needed to accumulate a per-pass
        # finite-key block under Lim et al. 2014 (see physics/finite_key.py).
        # The third ("vacuum") intensity is mu_3 = 0, for which D_3 = Y_0 and
        # E_3 = e_0 = 0.5 exactly, so Y_0 is all the caller needs for it.
        "vacuumYield": Y_0,                      # Y_0 = D_3
        "signalQber": E_s,                       # E_1 (fraction, not %)
        "decoyQber": E_d,                        # E_2 (fraction, not %)
        "mu_signal": mu_s,
        "mu_decoy": mu_d,
        "finiteKeyFraction": fk_fraction,
        "liveFraction": live_fraction,
        "protocol": "BB84-decoy",
    }




def calculate_qkd(
    protocol: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Route to the requested QKD protocol calculator."""
    key = (protocol or "bb84").strip().lower()
    if key == "bb84":
        return calculate_bb84(params)
    if key in ("bb84-decoy", "bb84decoy"):
        return calculate_bb84_decoy(params)
    if key == "e91":
        return calculate_e91(params)
    if key in ("cv-qkd", "cvqkd"):
        return calculate_cvqkd(params)
    if key in ("mdi-qkd", "mdiqkd", "mdi"):
        return calculate_mdiqkd(params)
    if key in ("tf-qkd", "tfqkd", "tf"):
        return calculate_tfqkd(params)
    return {"error": f"Unknown protocol: {protocol}"}
