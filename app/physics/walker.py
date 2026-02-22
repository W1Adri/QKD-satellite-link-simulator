# ---------------------------------------------------------------------------
# app/physics/walker.py
# ---------------------------------------------------------------------------
# Purpose : Walker-Delta constellation element generation and sun-synchronous
#           inclination computation.
#
# Functions:
#   generate_walker(T,P,F,a,i,e)              – list of Keplerian element dicts
#   sun_synchronous_inclination(alt, e)        – required inclination (°)
#   validate_sun_synchronous(alt, inc, e)      – check RAAN drift vs target
#   repeat_ground_track_sma(revs_per_day)      – semi-major axis for RGT
#   validate_elements(a, e, i)                 – feasibility check
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    DEG2RAD,
    EARTH_RADIUS_KM,
    J2,
    MAX_SEMI_MAJOR,
    MIN_SEMI_MAJOR,
    MU_EARTH,
    RAD2DEG,
    SIDEREAL_DAY,
    SOLAR_MEAN_MOTION,
)
from .propagation import compute_j2_secular_rates


def generate_walker(
    T: int,
    P: int,
    F: int,
    altitude_km: float,
    inclination_deg: float,
    eccentricity: float = 0.0,
    raan_offset_deg: float = 0.0,
) -> List[Dict[str, float]]:
    """Generate Keplerian element dicts for a Walker-Delta T/P/F constellation.

    Returns list of dicts with keys:
        semiMajor, eccentricity, inclination, raan, argPerigee, meanAnomaly  (all deg for angles).
    """
    if P <= 0 or T <= 0:
        return []
    S = T // P
    a = EARTH_RADIUS_KM + altitude_km
    sats: List[Dict[str, float]] = []
    for p in range(P):
        raan = (360.0 * p / P) + raan_offset_deg
        for s in range(S):
            m = (360.0 * s / S) + (360.0 * F * p / T)
            sats.append({
                "semiMajor": a,
                "eccentricity": eccentricity,
                "inclination": inclination_deg,
                "raan": raan % 360.0,
                "argPerigee": 0.0,
                "meanAnomaly": m % 360.0,
            })
    return sats


def sun_synchronous_inclination(
    altitude_km: float,
    eccentricity: float = 0.0,
) -> float:
    """Return the inclination (°) needed for a sun-synchronous orbit."""
    a = EARTH_RADIUS_KM + altitude_km
    req = SOLAR_MEAN_MOTION * DEG2RAD / 86400.0
    n = math.sqrt(MU_EARTH / a ** 3)
    p = a * (1 - eccentricity ** 2)
    factor = -1.5 * J2 * (EARTH_RADIUS_KM / p) ** 2 * n
    if abs(factor) < 1e-15:
        raise ValueError("Cannot compute sun-synchronous inclination")
    cos_i = req / factor
    if abs(cos_i) > 1.0:
        raise ValueError(
            f"No sun-synchronous orbit at {altitude_km:.1f} km "
            f"(cos i = {cos_i:.4f}).  Try 600–6000 km."
        )
    inc = math.acos(cos_i) * RAD2DEG
    return 180 - inc if inc < 90 else inc


def validate_sun_synchronous(
    altitude_km: float,
    inclination_deg: float,
    eccentricity: float = 0.0,
) -> Dict[str, Any]:
    """Check how close an orbit is to being sun-synchronous."""
    a = EARTH_RADIUS_KM + altitude_km
    rates = compute_j2_secular_rates(a, eccentricity, inclination_deg * DEG2RAD)
    drift = rates.dot_raan * RAD2DEG * 86400.0
    target = SOLAR_MEAN_MOTION
    err = abs(drift - target)
    return {
        "isSunSynchronous": err < 0.01,
        "raanDriftDegPerDay": drift,
        "targetDriftDegPerDay": target,
        "errorDegPerDay": drift - target,
        "errorPercent": (err / target) * 100 if target else 0,
    }


def repeat_ground_track_sma(
    revolutions_per_day: int,
    tolerance: float = 1e-6,
    max_iter: int = 100,
) -> Tuple[float, float]:
    """Iteratively compute semi-major axis for a repeat ground-track orbit.

    Returns (semi_major_axis_km, altitude_km).
    """
    target_n = 2.0 * math.pi * revolutions_per_day / SIDEREAL_DAY
    a = (MU_EARTH / target_n ** 2) ** (1.0 / 3.0)
    for _ in range(max_iter):
        factor = 1.5 * J2 * (EARTH_RADIUS_KM / a) ** 2
        n_pert = target_n * (1 + factor * 0.75)
        a_new = (MU_EARTH / n_pert ** 2) ** (1.0 / 3.0)
        if abs(a_new - a) < tolerance:
            a = a_new
            break
        a = a_new
    return a, a - EARTH_RADIUS_KM


def validate_elements(
    a: float,
    e: float,
    i_rad: float,
) -> Tuple[bool, Optional[str]]:
    """Check orbital element feasibility."""
    if a < EARTH_RADIUS_KM:
        return False, f"SMA {a:.1f} km below Earth surface"
    if a > 50_000:
        return False, f"SMA {a:.1f} km beyond practical limits"
    if e < 0 or e >= 1:
        return False, f"Eccentricity {e:.4f} outside [0,1)"
    perigee = a * (1 - e) - EARTH_RADIUS_KM
    if perigee < 150:
        return False, f"Perigee {perigee:.1f} km too low"
    if not 0 <= i_rad <= math.pi:
        return False, "Inclination outside [0, π]"
    return True, None
