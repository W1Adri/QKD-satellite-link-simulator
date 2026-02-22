# ---------------------------------------------------------------------------
# app/physics/kepler.py
# ---------------------------------------------------------------------------
# Purpose : Kepler equation solver and orbital-state-vector computation.
#
# Functions:
#   solve_kepler(M, e)           – iterative Newton-Raphson Kepler solver
#   orbital_position(a,e,i,…)   – position vector in ECI from Keplerian elements
#   orbital_position_velocity(…) – position + velocity vectors in ECI
#   perifocal_to_eci(…)         – rotation matrix from perifocal to ECI frame
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import List, Tuple

from .constants import MU_EARTH

TWO_PI = 2.0 * math.pi


def solve_kepler(
    mean_anomaly: float,
    eccentricity: float,
    tolerance: float = 1e-8,
    max_iter: int = 50,
) -> float:
    """Solve Kepler's equation  M = E - e·sin(E)  for eccentric anomaly *E*.

    Uses Newton-Raphson iteration.

    Args:
        mean_anomaly: Mean anomaly in radians.
        eccentricity: Orbital eccentricity [0, 1).
        tolerance: Convergence criterion (radians).
        max_iter: Safety cap on iterations.

    Returns:
        Eccentric anomaly *E* in radians.
    """
    E = mean_anomaly if eccentricity <= 0.8 else math.pi
    for _ in range(max_iter):
        f = E - eccentricity * math.sin(E) - mean_anomaly
        fp = 1.0 - eccentricity * math.cos(E)
        delta = f / fp
        E -= delta
        if abs(delta) < tolerance:
            break
    return E


def _perifocal_to_eci(
    r_pf: List[float],
    inc: float,
    raan: float,
    arg_pe: float,
) -> List[float]:
    """Rotate a vector from the perifocal frame to ECI."""
    cO, sO = math.cos(raan), math.sin(raan)
    cI, sI = math.cos(inc), math.sin(inc)
    cW, sW = math.cos(arg_pe), math.sin(arg_pe)

    R = [
        [cO * cW - sO * sW * cI, -cO * sW - sO * cW * cI, sO * sI],
        [sO * cW + cO * sW * cI, -sO * sW + cO * cW * cI, -cO * sI],
        [sW * sI, cW * sI, cI],
    ]
    x, y, z = r_pf
    return [
        R[0][0] * x + R[0][1] * y + R[0][2] * z,
        R[1][0] * x + R[1][1] * y + R[1][2] * z,
        R[2][0] * x + R[2][1] * y + R[2][2] * z,
    ]


def orbital_position(
    a: float,
    e: float,
    inc: float,
    raan: float,
    arg_pe: float,
    M: float,
) -> Tuple[List[float], float, float]:
    """Compute ECI position from Keplerian elements.

    Returns:
        Tuple of (r_eci [km], true_anomaly [rad], radius [km]).
    """
    M_norm = (M + TWO_PI) % TWO_PI
    E = solve_kepler(M_norm, e)
    cos_E, sin_E = math.cos(E), math.sin(E)
    sqrt_1me2 = math.sqrt(1.0 - e * e)

    nu = math.atan2(sqrt_1me2 * sin_E, cos_E - e)
    r = a * (1.0 - e * cos_E)
    pf = [r * math.cos(nu), r * math.sin(nu), 0.0]
    r_eci = _perifocal_to_eci(pf, inc, raan, arg_pe)
    return r_eci, nu, r


def orbital_position_velocity(
    a: float,
    e: float,
    inc: float,
    raan: float,
    arg_pe: float,
    M: float,
) -> Tuple[List[float], List[float], float, float, float]:
    """Compute ECI position **and** velocity from Keplerian elements.

    Returns:
        (r_eci, v_eci, true_anomaly, mean_motion, radius)
    """
    n = math.sqrt(MU_EARTH / (a ** 3))
    M_norm = (M + TWO_PI) % TWO_PI
    E = solve_kepler(M_norm, e)
    cos_E, sin_E = math.cos(E), math.sin(E)
    sqrt_1me2 = math.sqrt(1.0 - e * e)

    nu = math.atan2(sqrt_1me2 * sin_E, cos_E - e)
    r = a * (1.0 - e * cos_E)

    pf_r = [r * math.cos(nu), r * math.sin(nu), 0.0]
    coeff = math.sqrt(MU_EARTH / (a * (1.0 - e * e)))
    pf_v = [-coeff * math.sin(nu), coeff * (e + math.cos(nu)), 0.0]

    r_eci = _perifocal_to_eci(pf_r, inc, raan, arg_pe)
    v_eci = _perifocal_to_eci(pf_v, inc, raan, arg_pe)
    return r_eci, v_eci, nu, n, r
