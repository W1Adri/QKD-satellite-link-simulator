# ---------------------------------------------------------------------------
# app/physics/propagation.py
# ---------------------------------------------------------------------------
# Purpose : Full orbit propagation with J2 secular drift, ECI ↔ ECEF
#           conversions, and timeline generation.
#
# Functions:
#   compute_j2_secular_rates(a,e,i)         – RAAN / ω̇ / Ṁ from J2
#   compute_enhanced_secular_rates(a,e,i,…) – optionally include J3/J4
#   date_to_julian(dt)                      – datetime → Julian date
#   gmst_from_date(dt)                      – GMST angle in radians
#   rotate_eci_to_ecef(r, v, gmst)          – frame rotation
#   ecef_to_latlon(r_ecef)                  – Cartesian → geodetic
#   propagate_orbit(params)                 – full timeline propagation
#
# Inputs/Outputs:
#   propagate_orbit receives orbital elements + simulation settings and
#   returns a list of dicts with {t, r_eci, v_eci, r_ecef, v_ecef, lat, lon, alt}.
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    DEG2RAD,
    EARTH_RADIUS_KM,
    EARTH_ROT_RATE,
    J2,
    J3,
    J4,
    MAX_SEMI_MAJOR,
    MIN_SEMI_MAJOR,
    MU_EARTH,
    RAD2DEG,
    SIDEREAL_DAY,
)
from .kepler import orbital_position_velocity

TWO_PI = 2.0 * math.pi


# ── J2 secular rates ─────────────────────────────────────────────────────

@dataclass
class SecularRates:
    """Secular perturbation rates in rad/s."""
    dot_raan: float
    dot_arg_perigee: float
    dot_mean_anomaly: float
    mean_motion: float


def compute_j2_secular_rates(a: float, e: float, i: float) -> SecularRates:
    """Compute secular rates due to J2 perturbation.

    Args:
        a: semi-major axis (km)
        e: eccentricity
        i: inclination (rad)
    """
    if a <= 0:
        return SecularRates(0.0, 0.0, 0.0, 0.0)
    n = math.sqrt(MU_EARTH / (a ** 3))
    p = a * (1 - e * e)
    if p <= 0:
        return SecularRates(0.0, 0.0, 0.0, n)

    cos_i = math.cos(i)
    sin_i = math.sin(i)
    factor = -1.5 * J2 * (EARTH_RADIUS_KM / p) ** 2 * n

    dot_raan = factor * cos_i
    dot_arg_pe = factor * (2.5 * sin_i * sin_i - 2.0)
    eta = math.sqrt(1 - e * e)
    dot_M = factor * eta * (1.5 * sin_i * sin_i - 1.0) / (1 - e * e)
    return SecularRates(dot_raan, dot_arg_pe, dot_M, n)


def compute_enhanced_secular_rates(
    a: float,
    e: float,
    i: float,
    include_j3: bool = False,
    include_j4: bool = False,
) -> SecularRates:
    """J2 secular rates, optionally augmented with J3 / J4 corrections."""
    rates = compute_j2_secular_rates(a, e, i)
    if not include_j3 and not include_j4:
        return rates
    p = a * (1 - e * e)
    if p <= 0:
        return rates
    cos_i, sin_i = math.cos(i), math.sin(i)
    n = rates.mean_motion
    d_raan = rates.dot_raan
    d_arg = rates.dot_arg_perigee

    if include_j3 and abs(e) > 1e-6:
        f3 = 0.5 * J3 * (EARTH_RADIUS_KM / p) ** 3 * n * (EARTH_RADIUS_KM / p)
        d_arg += f3 * sin_i * (5 * cos_i ** 2 - 1) / e
    if include_j4:
        f4 = 0.75 * J4 * (EARTH_RADIUS_KM / p) ** 4 * n
        d_raan += f4 * cos_i * (1.5 - 2.5 * sin_i ** 2)
        d_arg += f4 * (3.5 - 7.5 * sin_i ** 2 + 6.25 * sin_i ** 4)
    return SecularRates(d_raan, d_arg, rates.dot_mean_anomaly, n)


# ── Epoch / sidereal helpers ─────────────────────────────────────────────

def date_to_julian(dt: datetime) -> float:
    """Convert a *datetime* to Julian Date (UTC)."""
    import calendar
    ts = calendar.timegm(dt.timetuple()) + dt.microsecond / 1e6
    return ts / 86400.0 + 2_440_587.5


def gmst_from_date(dt: datetime) -> float:
    """Return Greenwich Mean Sidereal Time in radians."""
    jd = date_to_julian(dt)
    d = jd - 2_451_545.0
    t = d / 36525.0
    gmst_deg = (280.46061837 + 360.98564736629 * d
                + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return (gmst_deg * DEG2RAD) % TWO_PI


# ── Frame conversions ────────────────────────────────────────────────────

def rotate_eci_to_ecef(
    r_eci: List[float],
    v_eci: List[float],
    gmst: float,
) -> Tuple[List[float], List[float]]:
    """Rotate ECI position+velocity to ECEF accounting for Earth rotation."""
    c, s = math.cos(gmst), math.sin(gmst)
    r_ecef = [c * r_eci[0] + s * r_eci[1],
              -s * r_eci[0] + c * r_eci[1],
              r_eci[2]]
    omega_cross = [
        -EARTH_ROT_RATE * r_ecef[1],
         EARTH_ROT_RATE * r_ecef[0],
         0.0,
    ]
    v_ecef = [
        c * v_eci[0] + s * v_eci[1] - omega_cross[0],
       -s * v_eci[0] + c * v_eci[1] - omega_cross[1],
        v_eci[2] - omega_cross[2],
    ]
    return r_ecef, v_ecef


def ecef_to_latlon(r: List[float]) -> Dict[str, float]:
    """Convert ECEF vector to {lat, lon, alt} (degrees / km)."""
    x, y, z = r
    lon = math.atan2(y, x) * RAD2DEG
    hyp = math.sqrt(x * x + y * y)
    lat = math.atan2(z, hyp) * RAD2DEG
    alt = math.sqrt(x * x + y * y + z * z) - EARTH_RADIUS_KM
    return {"lat": lat, "lon": ((lon + 540) % 360) - 180, "alt": alt}


def ecef_from_latlon(
    lat_deg: float,
    lon_deg: float,
    radius_km: float = EARTH_RADIUS_KM,
) -> List[float]:
    """Convert geodetic (lat, lon) to ECEF vector."""
    lat = lat_deg * DEG2RAD
    lon = lon_deg * DEG2RAD
    cl = math.cos(lat)
    return [radius_km * cl * math.cos(lon),
            radius_km * cl * math.sin(lon),
            radius_km * math.sin(lat)]


# ── Full orbit propagation ───────────────────────────────────────────────

def propagate_orbit(
    a: float,
    e: float,
    inc_deg: float,
    raan_deg: float,
    arg_pe_deg: float,
    M0_deg: float,
    j2_enabled: bool = True,
    epoch_iso: Optional[str] = None,
    samples_per_orbit: int = 180,
    total_orbits: int = 3,
) -> Dict[str, Any]:
    """Propagate an orbit over *total_orbits* revolutions.

    Returns dict with keys:
      semi_major, orbit_period, total_time, timeline, data_points, ground_track.
    """
    a = max(MIN_SEMI_MAJOR, min(a, MAX_SEMI_MAJOR))
    inc = inc_deg * DEG2RAD
    raan0 = raan_deg * DEG2RAD
    arg0 = arg_pe_deg * DEG2RAD
    M0 = M0_deg * DEG2RAD

    n = math.sqrt(MU_EARTH / a ** 3)
    period = TWO_PI / n
    total_time = period * total_orbits
    total_samples = max(2, samples_per_orbit * total_orbits)
    dt = total_time / (total_samples - 1)
    timeline = [i * dt for i in range(total_samples)]

    epoch_dt = datetime.utcnow()
    if epoch_iso:
        try:
            epoch_dt = datetime.fromisoformat(epoch_iso.rstrip("Z"))
        except ValueError:
            pass
    gmst0 = gmst_from_date(epoch_dt)

    dot_raan = dot_arg = 0.0
    if j2_enabled:
        rates = compute_j2_secular_rates(a, e, inc)
        dot_raan = rates.dot_raan
        dot_arg = rates.dot_arg_perigee

    data_points: List[Dict[str, Any]] = []
    ground_track: List[Dict[str, float]] = []

    for t in timeline:
        raan_t = raan0 + dot_raan * t
        arg_t = arg0 + dot_arg * t
        M = (M0 + n * t) % TWO_PI
        r_eci, v_eci, _nu, _n, _r = orbital_position_velocity(
            a, e, inc, raan_t, arg_t, M
        )
        gmst = (gmst0 + EARTH_ROT_RATE * t) % TWO_PI
        r_ecef, v_ecef = rotate_eci_to_ecef(r_eci, v_eci, gmst)
        geo = ecef_to_latlon(r_ecef)

        data_points.append({
            "t": t,
            "r_eci": r_eci,
            "v_eci": v_eci,
            "r_ecef": r_ecef,
            "v_ecef": v_ecef,
            "lat": geo["lat"],
            "lon": geo["lon"],
            "alt": geo["alt"],
            "gmst": gmst,
        })
        ground_track.append({"lat": geo["lat"], "lon": geo["lon"]})

    return {
        "semi_major": a,
        "orbit_period": period,
        "total_time": total_time,
        "timeline": timeline,
        "data_points": data_points,
        "ground_track": ground_track,
    }
