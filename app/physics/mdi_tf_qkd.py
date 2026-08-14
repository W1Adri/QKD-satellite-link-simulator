# ---------------------------------------------------------------------------
# app/physics/mdi_tf_qkd.py
# ---------------------------------------------------------------------------
# Purpose : Measurement-device-independent (MDI) and Twin-Field (TF) QKD
#           secure-key-rate calculators.  Both protocols place an *untrusted*
#           relay (Charlie) at the channel midpoint, so they are split out of
#           qkd.py (point-to-point protocols) into their own module.
#
# Functions:
#   calculate_mdiqkd(params) – MDI-QKD via Bell-state measurement (rate ∝ η)
#   calculate_tfqkd(params)  – Twin-Field QKD single-photon interference
#                              (rate ∝ √η — beats the repeaterless PLOB bound)
#
# References:
#   [Lo12]  Lo, Curty & Qi, PRL 108, 130503 (2012) – MDI-QKD.
#   [MR12]  Ma & Razavi, PRA 86, 052305 (2012)     – MDI-QKD rate / gains.
#   [Luc18] Lucamarini, Yuan, Dynes & Shields, Nature 557, 400 (2018) – TF-QKD.
#   [PLOB]  Pirandola et al., Nat. Commun. 8, 15043 (2017) – repeaterless bound.
#   [RMP09] Scarani et al., Rev. Mod. Phys. 81, 1301 (2009) – GLLP key rate.
#
# Both calculators assume a *symmetric* channel (Alice–Charlie and Bob–Charlie
# arms have equal loss), so each arm transmittance is √η where η is the total
# Alice↔Bob transmittance (channelLossdB).  Single-photon contributions assume
# an ideal decoy-state estimation of (Y₁₁, e₁₁) — the standard asymptotic
# treatment in [MR12]/[Luc18].
#
# Inputs (common): photonRate, channelLossdB, detectorEfficiency, darkCountRate.
# Outputs: {qber, rawKeyRate, secureKeyRate, channelTransmittance, protocol, …}
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict

from app.physics.finite_key import binary_entropy as _h, finite_key_fraction

_INFO_RECON_EFF = 1.16   # practical error-correction overhead (f_EC)
_QBER_THRESHOLD = 0.11   # one-photon QBER ceiling for a positive key rate
_E0 = 0.5                # error rate of a random (dark/background) click


def _common_inputs(params: Dict[str, Any], tag: str):
    """Parse the four shared inputs; return (vals, error) with error a dict|None."""
    try:
        photon_rate = float(params["photonRate"])
        loss_db = float(params["channelLossdB"])
        det_eff = float(params["detectorEfficiency"])
        dark_rate = float(params["darkCountRate"])
        bg_cps = float(params.get("backgroundCps", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        return None, {"error": f"Invalid {tag} input: {exc}"}
    if photon_rate <= 0 or loss_db < 0 or det_eff <= 0:
        return None, {"error": f"Invalid {tag} input: non-positive parameter"}
    return (photon_rate, loss_db, det_eff, dark_rate, bg_cps), None


def _apply_finite_key(params: Dict[str, Any], qber: float):
    """Optional composable finite-key fraction (Tomamichel 2012) at operating QBER."""
    finite_key_n = params.get("finite_key_n")
    if finite_key_n is None:
        return 1.0
    eps = float(params.get("epsilon_sec", 1e-10))
    return finite_key_fraction(float(finite_key_n), eps, qber)


# ── MDI-QKD ────────────────────────────────────────────────────────────────

def calculate_mdiqkd(params: Dict[str, Any]) -> Dict[str, Any]:
    """Measurement-device-independent QKD asymptotic secure key rate [Lo12].

    Alice and Bob each send weak coherent pulses of intensity μ to an untrusted
    relay performing a linear-optics Bell-state measurement (BSM).  Two of the
    four Bell states are distinguishable, so the BSM succeeds with probability
    ½·p_A·p_B per pulse pair (rate ∝ η).  The secure key is carried by events
    where both parties emitted a single photon [MR12, Lo12]:

        R = Q₁₁ [1 − h(e₁₁)] − Q_μ f_EC h(E_μ)            [Lo12, Eq. (1)]

    Single-photon-pair yield / gain (symmetric arms η_A = η_B = √η · η_det):

        Y₁₁ = η_A η_B / 2 + Y_dark,   Q₁₁ = (μ e^{−μ})² Y₁₁

    Optional keys: mu (0.5), e_optical (0.02), finite_key_n, epsilon_sec,
    backgroundCps.
    """
    vals, err = _common_inputs(params, "MDI-QKD")
    if err:
        return err
    photon_rate, loss_db, det_eff, dark_rate, bg_cps = vals
    mu = float(params.get("mu", 0.5))
    e_opt = float(params.get("e_optical", 0.02))
    if mu <= 0:
        return {"error": "mu must be > 0"}

    eta_ch = 10.0 ** (-loss_db / 10.0)            # total Alice↔Bob transmittance
    eta_arm = math.sqrt(eta_ch) * det_eff         # per-arm system efficiency
    # Dark + background probability per detector per gate (clamped to ½).
    p_d = min((dark_rate + bg_cps * det_eff) / photon_rate, 0.5)

    # Single-photon-pair contribution (ideal decoy estimation).
    y_signal = 0.5 * eta_arm * eta_arm            # successful BSM | 1+1 photons
    y_dark = 2.0 * p_d                            # random-coincidence floor
    Y_11 = y_signal + y_dark
    e_11 = (e_opt * y_signal + _E0 * y_dark) / Y_11 if Y_11 > 0 else _E0
    e_11 = max(0.0, min(e_11, 0.5))
    Q_11 = (mu * math.exp(-mu)) ** 2 * Y_11

    # Overall BSM gain Q_μ and Z-basis QBER E_μ (signal intensity).
    p_arm = 1.0 - (1.0 - p_d) * math.exp(-mu * eta_arm)   # per-arm click prob
    Q_mu = 0.5 * p_arm * p_arm
    q_noise = min(p_d, Q_mu)                              # random part of the gain
    E_mu = (e_opt * (Q_mu - q_noise) + _E0 * q_noise) / Q_mu if Q_mu > 0 else 0.5
    E_mu = max(0.0, min(E_mu, 0.5))

    # GLLP key rate per pulse pair [Lo12, Eq. (1)].
    pa_term = Q_11 * (1.0 - _h(e_11))
    ec_term = _INFO_RECON_EFF * Q_mu * _h(E_mu)
    skr_per_pulse = max(0.0, pa_term - ec_term)
    if e_11 > _QBER_THRESHOLD:
        skr_per_pulse = 0.0

    fk = _apply_finite_key(params, E_mu)
    skr_bps = skr_per_pulse * photon_rate * fk
    raw_bps = Q_mu * photon_rate

    return {
        "qber": E_mu * 100,
        "rawKeyRate": raw_bps / 1e3,
        "secureKeyRate": skr_bps / 1e3,
        "channelTransmittance": eta_ch,
        "detectionRate": Q_mu * photon_rate,
        # Sifted block rate [counts/s] = successful BSM events, the block that
        # enters EC+PA in the GLLP rate above (no extra sifting factor there).
        "siftedKeyRate": raw_bps,
        "singlePhotonGain": Q_11,
        "singlePhotonPhaseError": e_11 * 100,
        "signalGain": Q_mu,
        "mu": mu,
        "finiteKeyFraction": fk,
        "protocol": "MDI-QKD",
    }


# ── Twin-Field QKD ──────────────────────────────────────────────────────────

def calculate_tfqkd(params: Dict[str, Any]) -> Dict[str, Any]:
    """Twin-Field QKD asymptotic secure key rate [Luc18].

    Alice and Bob each send phase-randomised weak coherent pulses of per-arm
    intensity μ_arm to an untrusted relay performing *single-photon*
    interference (one click heralds a key event).  Because a heralding click
    needs only one photon to survive a single arm (transmittance √η), the gain
    — and hence the key rate — scales as O(√η), beating the repeaterless PLOB
    bound [PLOB] that limits point-to-point protocols to O(η).

        R = (1/2){ Q_μ [1 − h(e_X)] − Q_μ f_EC h(E_Z) }     [Luc18, Methods]

    with heralding gain Q_μ = 1 − (1 − Y₀) e^{−n̄}, n̄ = 2 μ_arm √η η_det the
    mean photon number reaching the relay detectors.  The ½ is the phase
    post-selection (basis sifting) factor.

    Optional keys: mu_arm (0.1), e_optical (0.02), finite_key_n, epsilon_sec,
    backgroundCps.
    """
    vals, err = _common_inputs(params, "TF-QKD")
    if err:
        return err
    photon_rate, loss_db, det_eff, dark_rate, bg_cps = vals
    mu_arm = float(params.get("mu_arm", 0.1))
    e_opt = float(params.get("e_optical", 0.02))
    if mu_arm <= 0:
        return {"error": "mu_arm must be > 0"}

    eta_ch = 10.0 ** (-loss_db / 10.0)            # total Alice↔Bob transmittance
    eta_arm = math.sqrt(eta_ch)                   # per-arm channel transmittance
    n_bar = 2.0 * mu_arm * eta_arm * det_eff      # mean photons at the relay (√η)

    Y_0 = min((dark_rate + bg_cps * det_eff) / photon_rate, 0.5)   # vacuum yield
    # Heralding (single-click) gain — scales as n̄ ∝ √η for small n̄.
    Q_mu = 1.0 - (1.0 - Y_0) * math.exp(-n_bar)

    # Errors: optical misalignment on the heralded signal + random dark clicks.
    vac = Y_0
    E_mu = (_E0 * vac + e_opt * (Q_mu - vac)) / Q_mu if Q_mu > 0 else 0.5
    E_mu = max(0.0, min(E_mu, 0.5))

    # Key rate per pulse (½ = phase post-selection) [Luc18, Methods].
    skr_per_pulse = 0.5 * max(
        0.0, Q_mu * (1.0 - (1.0 + _INFO_RECON_EFF) * _h(E_mu))
    )
    if E_mu > _QBER_THRESHOLD:
        skr_per_pulse = 0.0

    fk = _apply_finite_key(params, E_mu)
    skr_bps = skr_per_pulse * photon_rate * fk
    raw_bps = 0.5 * Q_mu * photon_rate

    return {
        "qber": E_mu * 100,
        "rawKeyRate": raw_bps / 1e3,
        "secureKeyRate": skr_bps / 1e3,
        "channelTransmittance": eta_ch,
        "detectionRate": Q_mu * photon_rate,
        # Sifted block rate [counts/s] = heralded events surviving the ½ phase
        # post-selection, matching the ½ already applied to the rate above.
        "siftedKeyRate": raw_bps,
        "heraldingGain": Q_mu,
        "meanPhotonRelay": n_bar,
        "armTransmittance": eta_arm,
        "mu_arm": mu_arm,
        "finiteKeyFraction": fk,
        "protocol": "TF-QKD",
    }
