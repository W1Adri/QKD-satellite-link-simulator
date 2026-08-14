# ---------------------------------------------------------------------------
# app/physics/finite_key.py
# ---------------------------------------------------------------------------
# Purpose : Composable finite-key security bounds for prepare-and-measure BB84.
#
# Implements the *tight* finite-key length of
#
#   M. Tomamichel, C. C. W. Lim, N. Gisin, R. Renner,
#   "Tight finite-key analysis for quantum cryptography",
#   Nature Communications 3, 634 (2012).  [arXiv:1103.4130]  [Tom12]
#
# Main result (their Eq. 2).  For a protocol Φ[n, k, ℓ, Q_tol, ε_cor, leak_EC]
# that measures n bits in the key basis (X) and k bits in the
# parameter-estimation basis (Z), the extractable ε-secret key length obeys
#
#   ℓ ≤ n (q − h(Q_tol + μ)) − leak_EC − log₂( 2 / (ε_sec² ε_cor) )
#
# with the parameter-estimation statistical fluctuation
#
#   μ = sqrt( (n + k)/(n k) · (k + 1)/k · ln(4/ε_sec) ),
#
# where q is the source preparation quality (q = 1 for ideal BB84), h is the
# binary Shannon entropy, and the total security is ε = ε_cor + ε_sec.
#
# Asymptotically (n, k → ∞ with k ∝ √n) μ → 0 and the log-term vanishes, so
# ℓ → n(q − h(Q)) − leak_EC, i.e. r_max = 1 − 2h(Q) for q = 1, leak_EC = n·h(Q).
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Optional


def binary_entropy(x: float) -> float:
    """Binary Shannon entropy h(x) = −x log₂x − (1−x) log₂(1−x)."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return -x * math.log2(x) - (1.0 - x) * math.log2(1.0 - x)


def phase_error_deviation(n: float, k: float, eps_sec: float = 1e-10) -> float:
    """Statistical fluctuation μ added to Q_tol ([Tom12] Eq. 2).

    Args:
        n: key-basis (X) detections used for the key.
        k: parameter-estimation (Z) basis detections.
        eps_sec: composable secrecy parameter.

    Returns the additive correction μ so the phase error rate is bounded by
    Q_tol + μ.  μ → 0 as n, k → ∞ (with k ∝ √n).  Worst case 0.5 if n,k ≤ 0.
    """
    if n <= 0.0 or k <= 0.0:
        return 0.5
    eps = min(max(eps_sec, 1e-20), 1.0)
    return math.sqrt(((n + k) / (n * k)) * ((k + 1.0) / k) * math.log(4.0 / eps))


def asymptotic_key_length_bb84(
    n: float,
    qber: float,
    *,
    q: float = 1.0,
    leak_ec: Optional[float] = None,
    f_ec: float = 1.16,
) -> float:
    """Asymptotic (M → ∞) key length: ℓ_∞ = n(q − h(Q)) − leak_EC."""
    if n <= 0.0:
        return 0.0
    qber = min(max(qber, 0.0), 0.5)
    if leak_ec is None:
        leak_ec = f_ec * n * binary_entropy(qber)
    return max(0.0, n * (q - binary_entropy(qber)) - leak_ec)


def finite_key_length_bb84(
    n: float,
    qber: float,
    *,
    k: Optional[float] = None,
    q: float = 1.0,
    leak_ec: Optional[float] = None,
    f_ec: float = 1.16,
    eps_sec: float = 1e-10,
    eps_cor: float = 1e-15,
) -> float:
    """Extractable ε-secret key length ℓ (bits), [Tom12] Eq. 2.

    Args:
        n: sifted key-basis (X) detections.
        qber: observed bit/channel error rate Q_tol (fraction, 0–0.5).
        k: parameter-estimation (Z) detections; defaults to n (symmetric bases).
        q: source preparation quality (1.0 = ideal BB84).
        leak_ec: error-correction leakage [bits]; defaults to f_ec·n·h(qber).
        f_ec: reconciliation inefficiency (1.16 typical).
        eps_sec: composable secrecy parameter.
        eps_cor: composable correctness parameter.

    Returns max(0, ℓ).
    """
    if n <= 0.0:
        return 0.0
    k_pe = n if k is None else k
    qber = min(max(qber, 0.0), 0.5)
    mu = phase_error_deviation(n, k_pe, eps_sec)
    if leak_ec is None:
        leak_ec = f_ec * n * binary_entropy(qber)
    eps_s = min(max(eps_sec, 1e-20), 1.0)
    eps_c = min(max(eps_cor, 1e-20), 1.0)
    finite_term = math.log2(2.0 / (eps_s * eps_s * eps_c))
    ell = n * (q - binary_entropy(qber + mu)) - leak_ec - finite_term
    return max(0.0, ell)


def finite_key_fraction(
    n_sifted: float,
    epsilon_sec: float = 1e-10,
    qber: float = 0.02,
    *,
    k: Optional[float] = None,
    q: float = 1.0,
    f_ec: float = 1.16,
    eps_cor: float = 1e-15,
) -> float:
    """Finite-key penalty as a fraction r ∈ [0, 1] of the asymptotic key.

    r = ℓ_finite(n) / ℓ_∞(n) using the [Tom12] bound, so an asymptotic secure
    key rate can be multiplied by r to obtain the finite-size rate.  This
    replaces the previous heuristic 1 − √(−8 ln ε)/√n with the full composable
    treatment (statistical fluctuation μ folded into the phase error, plus the
    log₂(2/(ε_sec² ε_cor)) privacy-amplification / correctness overhead).

    Args:
        n_sifted: sifted key-basis detections.
        epsilon_sec: composable secrecy parameter.
        qber: representative channel QBER for the penalty (BB84/decoy callers
            pass the operating QBER); default 0.02.
        k, q, f_ec, eps_cor: see finite_key_length_bb84.

    Returns 0.0 if n_sifted ≤ 0 or the asymptotic key is non-positive.
    """
    if n_sifted <= 0.0:
        return 0.0
    ell_inf = asymptotic_key_length_bb84(n_sifted, qber, q=q, f_ec=f_ec)
    if ell_inf <= 0.0:
        return 0.0
    ell_fin = finite_key_length_bb84(
        n_sifted, qber, k=k, q=q, f_ec=f_ec,
        eps_sec=epsilon_sec, eps_cor=eps_cor,
    )
    return max(0.0, min(1.0, ell_fin / ell_inf))


# ═══════════════════════════════════════════════════════════════════════════
# DECOY-STATE BB84 — Lim et al. 2014
# ═══════════════════════════════════════════════════════════════════════════
#
#   C. C. W. Lim, M. Curty, N. Walenta, F. Xu, H. Zbinden,
#   "Concise security bounds for practical decoy-state quantum key
#    distribution", Phys. Rev. A 89, 022307 (2014).  arXiv:1311.7129.  [Lim14]
#
# WHY THIS EXISTS SEPARATELY FROM THE [Tom12] BOUND ABOVE
# -------------------------------------------------------
# [Tom12] is a bound for BB84 with a *single-photon* source and rules out its
# own use for weak coherent pulses in its Device Model section: "an ideal
# implementation therefore requires a single-photon source in Alice's
# laboratory.  In order to take into account sources that emit weak coherent
# light pulses instead, the analysis presented in this paper can be extended
# using photon tagging and decoy states.  This approach — although beyond the
# scope of the present article — can be incorporated into our finite-key
# analysis."  Applying finite_key_fraction() to a decoy-state rate therefore
# OVERESTIMATES the key: measured against [Lim14] at the intensities this
# project uses, by 1.7-3.4x at n_X = 1e6, and at n_X = 1e5 the rigorous decoy
# key is exactly zero where the [Tom12] fraction still returns ~0.85.  It also
# cannot move the zero-key threshold at all (a multiplicative factor is
# positive wherever the asymptotic rate is), leaving ~7-13 dB of loss margin
# that does not exist — precisely the low-elevation wings of a satellite pass.
#
# [Tom12] remains correct, and is kept above, for genuine single-photon BB84.
#
# PROTOCOL
# --------
# Efficient (biased-basis) BB84 with phase-randomised weak coherent pulses.
# Three intensities K = {mu_1, mu_2, mu_3} with mu_1 > mu_2 + mu_3 and
# mu_2 > mu_3 >= 0; mu_3 = 0 is the vacuum decoy ("weak + vacuum").  The key is
# extracted from the X basis; the Z basis serves only for phase-error
# estimation.  One satellite pass = one block, which is the published
# convention — Islam et al., PRX Quantum 5, 030101 (2024) Sec. III B: "the key
# is extracted from data for the whole pass as a single block without
# partitioning".
#
# EPSILON BUDGET
# --------------
# [Lim14] Eq. (B4) with alpha_4 = alpha_5 = 0 gives
#     eps_sec = 2(2 alpha_1 + alpha_2 + alpha_3) + nu + 10 eps_1 + 2 eps_2,
# i.e. twelve concentration uses (10 on counts, 2 on errors) plus smoothing.
# Setting every term to a common eps yields eps_sec = 21 eps, hence the
# -6 log2(21/eps_sec) tail in Eq. (1).  This module uses that convention:
# every internal failure probability is eps_sec / _LIM_EPS_TERMS.
# ═══════════════════════════════════════════════════════════════════════════

_LIM_EPS_TERMS = 21.0   # [Lim14] Eq. (B4): eps_sec = 21 eps
_LN2 = math.log(2.0)


def hoeffding_delta(n_total: float, eps: float) -> float:
    """Hoeffding deviation delta(n, eps) = sqrt((n/2) ln(1/eps)) ([Lim14] Eq. A2).

    Args:
        n_total: the TOTAL count the deviation is scaled by (n_X for count
            bounds, m_Z for error bounds).  [Lim14] deliberately uses the total
            rather than the per-intensity count — that is the loose step in
            their derivation, and replacing it with a per-intensity Chernoff
            bound (Yin et al., PRA 101, 062521 (2020) Eqs. 9-10, as used by
            Sidhu et al., npj Quantum Inf. 8, 18 (2022) Eqs. 7-8) is strictly
            key-increasing.  Not done here: this module reproduces the
            published [Lim14] bound so results trace to Eqs. (1)-(5) verbatim.
        eps: per-use failure probability (eps_sec / 21).
    """
    if n_total <= 0.0:
        return 0.0
    e = min(max(eps, 1e-300), 1.0)
    return math.sqrt(0.5 * n_total * math.log(1.0 / e))


def tau_photon(n: int, intensities: tuple, probs: tuple) -> float:
    """Probability that Alice emits an n-photon state ([Lim14], tau_n).

        tau_n = sum_k e^{-mu_k} mu_k^n p_k / n!
    """
    total = 0.0
    fact = math.factorial(n)
    for mu, p in zip(intensities, probs):
        total += math.exp(-mu) * (mu ** n) * p / fact
    return total


def _gamma(a: float, b: float, c: float, d: float) -> float:
    """Random-sampling-without-replacement term of [Lim14] Eq. (5).

        gamma(a,b,c,d) = sqrt( [(c+d)(1-b)b / (c d ln2)]
                               * log2[ ((c+d)/(c d (1-b) b)) * (21^2/a^2) ] )

    From Fung, Ma & Chau, PRA 81, 012318 (2010).  ``a`` is eps_sec, ``b`` the
    Z-basis single-photon error rate, ``c`` = s_Z1, ``d`` = s_X1.  Note ln2 is
    the natural log of 2 while the outer log is base 2 — both appear in the
    printed formula and mixing them up is the classic implementation error.
    """
    if c <= 0.0 or d <= 0.0:
        return 0.5
    if b <= 0.0 or b >= 1.0:
        return 0.5
    a = min(max(a, 1e-300), 1.0)
    prefactor = (c + d) * (1.0 - b) * b / (c * d * _LN2)
    inner = ((c + d) / (c * d * (1.0 - b) * b)) * (_LIM_EPS_TERMS ** 2 / a ** 2)
    if inner <= 1.0 or prefactor <= 0.0:
        return 0.5
    return math.sqrt(prefactor * math.log2(inner))


def lim2014_key_length(
    n_x_k: tuple,
    n_z_k: tuple,
    m_z_k: tuple,
    m_x: float,
    *,
    intensities: tuple,
    probs: tuple,
    eps_sec: float = 1e-10,
    eps_cor: float = 1e-15,
    f_ec: float = 1.16,
    asymptotic: bool = False,
) -> dict:
    """Extractable secret-key length for decoy-state BB84 ([Lim14] Eqs. 1-5).

    Args:
        n_x_k: sifted X-basis (key) detections per intensity, (k1, k2, k3).
        n_z_k: sifted Z-basis (parameter-estimation) detections per intensity.
        m_z_k: Z-basis bit ERRORS per intensity.
        m_x:   X-basis bit errors in total (drives the EC leakage).
        intensities: (mu_1, mu_2, mu_3) with mu_1 > mu_2 + mu_3, mu_2 > mu_3 >= 0.
        probs: (p_1, p_2, p_3), the intensity-selection probabilities.
        eps_sec: composable secrecy parameter.
        eps_cor: composable correctness parameter.
        f_ec: reconciliation inefficiency; leak_EC = f_ec n_X h(E_X).
        asymptotic: if True, drop every statistical-fluctuation and tail term
            (delta -> 0, gamma -> 0, no -6log2(21/eps_sec) - log2(2/eps_cor)).
            This gives the N -> infinity limit of the SAME protocol, which is
            the correct denominator for a finite-size penalty ratio — comparing
            against a differently-sifted asymptotic model would fold a protocol
            change into what is meant to be a finite-size effect.

    Returns:
        Dict with ``ell`` (bits, >= 0) plus the intermediate bounds
        ``s_x0``, ``s_x1``, ``s_z1``, ``v_z1``, ``phi_x``, ``lambda_ec``,
        ``n_x``, ``tail_bits`` and ``ok`` (False when the bound collapsed).
    """
    mu_1, mu_2, mu_3 = (float(x) for x in intensities)
    zero = {
        "ell": 0.0, "s_x0": 0.0, "s_x1": 0.0, "s_z1": 0.0, "v_z1": 0.0,
        "phi_x": 0.5, "lambda_ec": 0.0, "n_x": 0.0, "tail_bits": 0.0,
        "ok": False,
    }
    # [Lim14] intensity ordering is a precondition of Eqs. (2)-(4), not a
    # preference: violating it flips the sign of their denominators.
    if not (mu_1 > mu_2 + mu_3 and mu_2 > mu_3 >= 0.0):
        return zero

    n_x = float(sum(n_x_k))
    n_z = float(sum(n_z_k))
    m_z = float(sum(m_z_k))
    if n_x <= 0.0 or n_z <= 0.0:
        return zero

    eps = float(eps_sec) / _LIM_EPS_TERMS
    d_count_x = 0.0 if asymptotic else hoeffding_delta(n_x, eps)
    d_count_z = 0.0 if asymptotic else hoeffding_delta(n_z, eps)
    d_err_z = 0.0 if asymptotic else hoeffding_delta(m_z, eps)

    def _bounds(counts: tuple, delta: float) -> tuple:
        """(n^-_k, n^+_k) per [Lim14] Eqs. (A7)-(A10)."""
        lo, hi = [], []
        for mu, p, c in zip(intensities, probs, counts):
            if p <= 0.0:
                lo.append(0.0)
                hi.append(0.0)
                continue
            scale = math.exp(mu) / p
            lo.append(max(0.0, scale * (float(c) - delta)))
            hi.append(scale * (float(c) + delta))
        return tuple(lo), tuple(hi)

    nx_lo, nx_hi = _bounds(n_x_k, d_count_x)
    nz_lo, nz_hi = _bounds(n_z_k, d_count_z)
    mz_lo, mz_hi = _bounds(m_z_k, d_err_z)

    tau_0 = tau_photon(0, intensities, probs)
    tau_1 = tau_photon(1, intensities, probs)
    if tau_0 <= 0.0 or tau_1 <= 0.0:
        return zero

    def _s0(lo: tuple, hi: tuple) -> float:
        """[Lim14] Eq. (2): vacuum events in a basis."""
        num = mu_2 * lo[2] - mu_3 * hi[1]
        return max(0.0, tau_0 * num / (mu_2 - mu_3))

    def _s1(lo: tuple, hi: tuple, s0: float) -> float:
        """[Lim14] Eq. (3): single-photon events in a basis."""
        denom = mu_1 * (mu_2 - mu_3) - mu_2 ** 2 + mu_3 ** 2
        if abs(denom) < 1e-30:
            return 0.0
        inner = (
            lo[1] - hi[2]
            - ((mu_2 ** 2 - mu_3 ** 2) / mu_1 ** 2) * (hi[0] - s0 / tau_0)
        )
        return max(0.0, tau_1 * mu_1 * inner / denom)

    s_x0 = _s0(nx_lo, nx_hi)
    s_x1 = _s1(nx_lo, nx_hi, s_x0)
    s_z0 = _s0(nz_lo, nz_hi)
    s_z1 = _s1(nz_lo, nz_hi, s_z0)
    if s_x1 <= 0.0 or s_z1 <= 0.0:
        return zero

    # [Lim14] Eq. (4): single-photon bit errors in Z.
    v_z1 = max(0.0, tau_1 * (mz_hi[1] - mz_lo[2]) / (mu_2 - mu_3))

    # [Lim14] Eq. (5): single-photon PHASE error rate in X.
    b = v_z1 / s_z1
    if b >= 1.0:
        return zero
    phi_x = b if asymptotic else b + _gamma(float(eps_sec), b, s_z1, s_x1)
    phi_x = max(0.0, min(phi_x, 0.5))
    if phi_x >= 0.5:
        return zero

    # Error-correction leakage.  leak_EC = f_ec n_X h(E_X) is [Lim14]'s own
    # choice for their figures.  The block-size-dependent form of Tomamichel,
    # Martinez-Mateo, Pacher & Elkouss, Quantum Inf. Process. 16, 280 (2017)
    # is tighter but needs an inverse binomial CDF; not used here.
    e_x = min(max(m_x / n_x, 0.0), 0.5) if n_x > 0.0 else 0.5
    lambda_ec = f_ec * n_x * binary_entropy(e_x)

    if asymptotic:
        tail = 0.0
    else:
        es = min(max(float(eps_sec), 1e-300), 1.0)
        ec = min(max(float(eps_cor), 1e-300), 1.0)
        tail = (
            6.0 * math.log2(_LIM_EPS_TERMS / es)
            + math.log2(2.0 / ec)
        )

    # [Lim14] Eq. (1).
    ell = s_x0 + s_x1 * (1.0 - binary_entropy(phi_x)) - lambda_ec - tail
    return {
        "ell": max(0.0, ell),
        "s_x0": s_x0,
        "s_x1": s_x1,
        "s_z1": s_z1,
        "v_z1": v_z1,
        "phi_x": phi_x,
        "lambda_ec": lambda_ec,
        "n_x": n_x,
        "tail_bits": tail,
        "ok": ell > 0.0,
    }


def lim2014_finite_fraction(
    n_x_k: tuple,
    n_z_k: tuple,
    m_z_k: tuple,
    m_x: float,
    *,
    intensities: tuple,
    probs: tuple,
    eps_sec: float = 1e-10,
    eps_cor: float = 1e-15,
    f_ec: float = 1.16,
) -> dict:
    """Finite-size penalty r = ell_finite / ell_asymptotic for decoy BB84.

    Both numerator and denominator are [Lim14] Eq. (1) evaluated on the SAME
    accumulated counts and the SAME protocol, the denominator with every
    fluctuation and tail term removed.  The ratio is therefore a pure
    finite-size effect, safe to apply multiplicatively to a pass-integrated
    asymptotic key volume computed elsewhere.

    Unlike :func:`finite_key_fraction`, this CAN return exactly 0.0 — which is
    the point: in satellite QKD the finite-key effect is a threshold effect,
    and a bound that is positive wherever the asymptotic rate is positive
    invents loss margin that does not exist.

    Returns:
        Dict with ``fraction`` in [0, 1], ``ell_finite``, ``ell_asymptotic``,
        ``n_x`` and ``phi_x``.
    """
    fin = lim2014_key_length(
        n_x_k, n_z_k, m_z_k, m_x, intensities=intensities, probs=probs,
        eps_sec=eps_sec, eps_cor=eps_cor, f_ec=f_ec, asymptotic=False,
    )
    asym = lim2014_key_length(
        n_x_k, n_z_k, m_z_k, m_x, intensities=intensities, probs=probs,
        eps_sec=eps_sec, eps_cor=eps_cor, f_ec=f_ec, asymptotic=True,
    )
    ell_inf = asym["ell"]
    frac = 0.0 if ell_inf <= 0.0 else max(0.0, min(1.0, fin["ell"] / ell_inf))
    return {
        "fraction": frac,
        "ell_finite": fin["ell"],
        "ell_asymptotic": ell_inf,
        "n_x": fin["n_x"] or asym["n_x"],
        "phi_x": fin["phi_x"],
    }
