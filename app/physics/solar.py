# ---------------------------------------------------------------------------
# app/physics/solar.py
# ---------------------------------------------------------------------------
# Purpose : Compute the Sun direction in the ECI (J2000 equatorial) frame and
#           derived quantities (sub-solar point) for a sequence of timestamps.
#           Uses the cosinekitty *astronomy-engine* library for high-accuracy
#           ephemeris (< 1 arc-minute) with zero external data files.
#
# Main functions:
#   compute_solar_ephemeris(epoch_iso, t_offsets_s)
#       → dict with sun_dir_eci[], gmst_rad[], subsolar_lat_lon[]
#   sun_direction_eci(t: astronomy.Time) → (x, y, z) unit vector
#   subsolar_point(t: astronomy.Time)    → (lat_deg, lon_deg)
#
# Coordinate frame:
#   ECI J2000 equatorial — +X vernal equinox, +Z celestial north pole,
#   +Y completes right-hand system.  Same frame used by propagation.py.
#
# Inputs  : ISO-8601 epoch string, array of offsets in seconds.
# Outputs : Parallel arrays of unit vectors, GMST angles, sub-solar (lat/lon).
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Tuple

import astronomy          # astronomy-engine (cosinekitty)

# ── Public API ──────────────────────────────────────────────────────────────

def compute_solar_ephemeris(
    epoch_iso: str,
    t_offsets_s: List[float],
) -> dict:
    """Compute sun direction in ECI and related data for each timestep.

    Parameters
    ----------
    epoch_iso : str
        ISO-8601 timestamp for the reference epoch (e.g. "2025-03-20T12:00:00Z").
    t_offsets_s : list[float]
        Time offsets in seconds from *epoch_iso*.

    Returns
    -------
    dict with keys:
        times_iso       – list[str]  ISO timestamps
        sun_dir_eci     – list[[x,y,z]]  unit vectors Earthâ†'Sun in ECI
        gmst_rad        – list[float]  Greenwich Mean Sidereal Time (rad)
        subsolar_lat_lon – list[[lat,lon]]  sub-solar point (deg)
    """
    epoch_dt = _parse_iso(epoch_iso)

    times_iso: list[str] = []
    sun_dirs: list[list[float]] = []
    gmst_rads: list[float] = []
    subsolar: list[list[float]] = []

    for dt_s in t_offsets_s:
        dt_obj = datetime.fromtimestamp(
            epoch_dt.timestamp() + dt_s, tz=timezone.utc
        )
        t = _to_astro_time(dt_obj)

        sx, sy, sz = sun_direction_eci(t)
        gmst = _gmst_rad(t)
        lat, lon = subsolar_point_from_dir(sx, sy, sz, gmst)

        times_iso.append(dt_obj.isoformat())
        sun_dirs.append([_r6(sx), _r6(sy), _r6(sz)])
        gmst_rads.append(_r6(gmst))
        subsolar.append([_r6(lat), _r6(lon)])

    return {
        "times_iso": times_iso,
        "sun_dir_eci": sun_dirs,
        "gmst_rad": gmst_rads,
        "subsolar_lat_lon": subsolar,
    }


def sun_direction_eci(t: astronomy.Time) -> Tuple[float, float, float]:
    """Return the Earth→Sun unit vector in J2000 ECI equatorial frame.

    Uses astronomy-engine's equatorial coordinates of the Sun as seen from
    Earth, converted from right-ascension / declination to Cartesian.
    """
    # GeoVector gives geocentric equatorial (J2000) position of the Sun in AU
    vec = astronomy.GeoVector(astronomy.Body.Sun, t, aberration=True)
    norm = math.sqrt(vec.x ** 2 + vec.y ** 2 + vec.z ** 2)
    if norm < 1e-12:
        return (1.0, 0.0, 0.0)
    return (vec.x / norm, vec.y / norm, vec.z / norm)


def subsolar_point_from_dir(
    sx: float, sy: float, sz: float, gmst_rad: float
) -> Tuple[float, float]:
    """Derive sub-solar latitude/longitude from ECI sun direction + GMST.

    Returns (latitude_deg, longitude_deg) with longitude in [-180, 180].
    """
    # Declination = latitude of subsolar point
    lat_rad = math.asin(max(-1.0, min(1.0, sz)))

    # Right ascension in ECI
    ra_rad = math.atan2(sy, sx)

    # Geographic longitude = RA − GMST
    lon_rad = ra_rad - gmst_rad
    # Wrap to [-π, π]
    lon_rad = (lon_rad + math.pi) % (2 * math.pi) - math.pi

    return (math.degrees(lat_rad), math.degrees(lon_rad))


# ── Internal helpers ────────────────────────────────────────────────────────

def _parse_iso(iso_str: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware UTC datetime."""
    iso_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_astro_time(dt: datetime) -> astronomy.Time:
    """Convert a Python datetime to an astronomy-engine Time object."""
    utc = dt.astimezone(timezone.utc)
    return astronomy.Time.Make(
        utc.year, utc.month, utc.day,
        utc.hour, utc.minute, utc.second + utc.microsecond / 1e6,
    )


def _gmst_rad(t: astronomy.Time) -> float:
    """Compute Greenwich Mean Sidereal Time in radians.

    Uses the standard IAU formula for GMST based on Julian UT1 date.
    Same algorithm as propagation.py → gmst_from_date() for consistency.
    """
    jd_ut1 = t.ut
    T = (jd_ut1 - 2451545.0) / 36525.0
    # GMST in seconds of time (IAU 1982 / Meeus)
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600 + 8640184.812866) * T
        + 0.093104 * T ** 2
        - 6.2e-6 * T ** 3
    )
    gmst_rad = (gmst_sec % 86400) / 86400 * 2 * math.pi
    if gmst_rad < 0:
        gmst_rad += 2 * math.pi
    return gmst_rad


def compute_scene_timeline(
    epoch_iso: str,
    interval_s: float,
    step_s: float,
) -> dict:
    """Compute Earth heliocentric position + solar data for a time range.

    Used by the Sun-centred (annual) 3D mode.  Returns parallel arrays
    aligned to the generated time offsets.

    Parameters
    ----------
    epoch_iso : str
        ISO-8601 reference epoch.
    interval_s : float
        Total interval duration in seconds (e.g. 86400 for 1 day).
    step_s : float
        Time between samples in seconds (e.g. 3600 for 1 h).

    Returns
    -------
    dict with keys:
        t_offsets_s       – list[float]   time offsets from epoch (seconds)
        earth_pos_eci_au  – list[[x,y,z]] Earth heliocentric position (AU, J2000 ECI)
        sun_dir_eci       – list[[x,y,z]] unit vector Earth→Sun (J2000 ECI)
        gmst_rad          – list[float]   Greenwich Mean Sidereal Time (rad)
    """
    if step_s <= 0:
        step_s = max(interval_s / 1000, 60.0)

    n_samples = int(interval_s / step_s) + 1
    # Safety cap
    if n_samples > 10000:
        n_samples = 10000
        step_s = interval_s / (n_samples - 1)

    epoch_dt = _parse_iso(epoch_iso)

    t_offsets: list[float] = []
    earth_pos: list[list[float]] = []
    sun_dirs: list[list[float]] = []
    gmst_rads: list[float] = []

    for idx in range(n_samples):
        dt_s = idx * step_s
        dt_obj = datetime.fromtimestamp(
            epoch_dt.timestamp() + dt_s, tz=timezone.utc
        )
        t = _to_astro_time(dt_obj)

        # Earth heliocentric position (AU, J2000 equatorial)
        ev = astronomy.HelioVector(astronomy.Body.Earth, t)
        earth_pos.append([_r6(ev.x), _r6(ev.y), _r6(ev.z)])

        # Sun direction from Earth (unit vector)
        sx, sy, sz = sun_direction_eci(t)
        sun_dirs.append([_r6(sx), _r6(sy), _r6(sz)])

        # GMST
        gmst = _gmst_rad(t)
        gmst_rads.append(_r6(gmst))

        t_offsets.append(round(dt_s, 3))

    return {
        "t_offsets_s": t_offsets,
        "earth_pos_eci_au": earth_pos,
        "sun_dir_eci": sun_dirs,
        "gmst_rad": gmst_rads,
    }


def _r6(val: float) -> float:
    """Round to 6 decimal places to keep JSON compact."""
    return round(val, 6)
