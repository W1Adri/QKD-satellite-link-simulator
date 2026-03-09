# ---------------------------------------------------------------------------
# app/physics/qkd.py
# ---------------------------------------------------------------------------
# Purpose : Quantum Key Distribution secure-key-rate calculators for the
#           three supported protocols: BB84, E91 (entanglement) and CV-QKD.
#
# Functions:
#   calculate_bb84(params)    – decoy-state BB84 key rate
#   calculate_e91(params)     – entanglement-based E91 key rate
#   calculate_cvqkd(params)   – continuous-variable Gaussian modulation
#   calculate_qkd(protocol, params) – dispatcher
#
# Inputs (common): photonRate, channelLossdB, detectorEfficiency,
#                  darkCountRate.
# Outputs: {qber, rawKeyRate, secureKeyRate, channelTransmittance, protocol}
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict, Optional


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
    mu = 0.5                                  # mean photon number
    det_rate = photon_rate * eta * det_eff * math.exp(-mu)

    # Shot noise model: signal shot noise + stray-light shot noise + dark counts
    signal_shot = det_rate                    # Poisson: variance = mean
    stray_shot = bg_cps * det_eff
    total_noise = dark_rate + stray_shot      # noise floor (excluding signal)
    noise = total_noise / 2.0

    qber = noise / (det_rate + noise) if (det_rate + noise) > 0 else 1.0

    sift = 0.5
    sifted = (det_rate + noise) * sift
    pa_cost = _h(qber) * sifted
    ec_leak = _INFO_RECON_EFF * _h(qber) * sifted
    skr = max(0.0, sifted - pa_cost - ec_leak)
    if qber > _QBER_THRESHOLD_BB84:
        skr = 0.0

    return {
        "qber": qber * 100,
        "rawKeyRate": sifted / 1000,
        "secureKeyRate": skr / 1000,
        "channelTransmittance": eta,
        "detectionRate": det_rate,
        "siftedKeyRate": sifted,
        "signalShotNoiseCps": signal_shot,
        "strayNoiseCps": stray_shot,
        "totalNoiseCps": total_noise,
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


# ── Dispatcher ───────────────────────────────────────────────────────────

def calculate_qkd(
    protocol: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Route to the requested QKD protocol calculator."""
    key = (protocol or "bb84").strip().lower()
    if key == "bb84":
        return calculate_bb84(params)
    if key == "e91":
        return calculate_e91(params)
    if key in ("cv-qkd", "cvqkd"):
        return calculate_cvqkd(params)
    return {"error": f"Unknown protocol: {protocol}"}
