# ---------------------------------------------------------------------------
# app/routers/orbital.py
# ---------------------------------------------------------------------------
# Purpose : Orbital-mechanics utility endpoints (sun-synchronous inclination,
#           Walker constellation, repeat ground track).
#
# Endpoints:
#   GET /api/orbital/info               – capabilities summary
#   GET /api/orbital/sun-synchronous    – inclination for SSO
#   GET /api/orbital/walker-constellation – Walker element set
#   GET /api/orbital/repeat-ground-track  – SMA for RGT orbit
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..physics.constants import DEG2RAD, EARTH_RADIUS_KM, J2, J3, J4, MU_EARTH, RAD2DEG
from ..physics.propagation import compute_j2_secular_rates
from ..physics.walker import (
    compute_sso_orbit,
    generate_walker,
    ltan_to_raan,
    repeat_ground_track_sma,
    sun_synchronous_inclination,
    validate_elements,
)

router = APIRouter(prefix="/api/orbital", tags=["Orbital"])


@router.get("/info")
async def orbital_info() -> Dict[str, Any]:
    return {
        "j2_available": True,
        "j3_j4_available": True,
        "sun_synchronous_calculation": True,
        "sun_synchronous_orbit_design": True,
        "walker_constellation": True,
        "repeat_ground_track": True,
        "constants": {
            "mu_earth": MU_EARTH,
            "earth_radius": EARTH_RADIUS_KM,
            "j2": J2, "j3": J3, "j4": J4,
        },
    }


@router.get("/sun-synchronous")
async def calc_sun_sync(altitude_km: float, eccentricity: float = 0.0):
    try:
        inc = sun_synchronous_inclination(altitude_km, eccentricity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    a = EARTH_RADIUS_KM + altitude_km
    rates = compute_j2_secular_rates(a, eccentricity, inc * DEG2RAD)
    import math
    return {
        "altitude_km": altitude_km,
        "eccentricity": eccentricity,
        "inclination_deg": inc,
        "semi_major_axis_km": a,
        "period_seconds": 2 * math.pi * math.sqrt(a ** 3 / MU_EARTH),
        "raan_drift_deg_per_day": rates.dot_raan * 86400 * RAD2DEG,
        "is_sun_synchronous": True,
    }


@router.get("/sun-synchronous-orbit")
async def design_sso(
    altitude_km: float,
    eccentricity: float = 0.0,
    ltan_hours: float = 10.5,
    epoch: Optional[str] = None,
):
    """Design a complete Sun-Synchronous Orbit.

    Returns full orbital elements including RAAN derived from LTAN, plus
    SSO metadata such as orbit class and RAAN drift rate.
    """
    try:
        result = compute_sso_orbit(altitude_km, eccentricity, ltan_hours, epoch)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.get("/walker-constellation")
async def walker_constellation(
    T: int, P: int, F: int,
    altitude_km: float, inclination_deg: float,
    eccentricity: float = 0.0,
):
    if T <= 0 or P <= 0 or F < 0 or F >= P:
        raise HTTPException(400, "Invalid Walker params (T>0, P>0, 0≤F<P).")
    elems = generate_walker(T, P, F, altitude_km, inclination_deg, eccentricity)
    import math
    sats = []
    for idx, el in enumerate(elems):
        a = el["semiMajor"]
        valid, err = validate_elements(a, el["eccentricity"], el["inclination"] * DEG2RAD)
        sats.append({
            "id": idx, **el,
            "period_seconds": 2 * math.pi * math.sqrt(a ** 3 / MU_EARTH),
            "valid": valid, "error": err,
        })
    return {
        "constellation_type": "Walker-Delta",
        "parameters": {"T": T, "P": P, "F": F},
        "altitude_km": altitude_km,
        "inclination_deg": inclination_deg,
        "total_satellites": len(sats),
        "satellites_per_plane": T // P,
        "satellites": sats,
    }


@router.get("/repeat-ground-track")
async def repeat_ground_track(revolutions_per_day: int):
    if revolutions_per_day <= 0 or revolutions_per_day > 20:
        raise HTTPException(400, "Revolutions per day must be 1–20.")
    a, alt = repeat_ground_track_sma(revolutions_per_day)
    return {
        "revolutions_per_day": revolutions_per_day,
        "semi_major_axis_km": a,
        "altitude_km": alt,
        "period_hours": 24.0 / revolutions_per_day,
    }
