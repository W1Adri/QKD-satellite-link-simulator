# ---------------------------------------------------------------------------
# app/physics/irradiance.py
# ---------------------------------------------------------------------------
# Purpose : Analytical model for solar irradiance at a ground station.
#           Computes Global Horizontal Irradiance (GHI), Direct Normal
#           Irradiance (DNI), and Diffuse Horizontal Irradiance (DHI) from
#           first principles using solar geometry and a clear-sky model.
#
# Model   : Based on the Ineichen–Perez clear-sky model simplified for
#           broadband irradiance.  Accounts for:
#             • Solar declination & hour angle → solar elevation / zenith
#             • Atmospheric extinction via air mass (Kasten & Young 1989)
#             • Altitude correction for station elevation
#             • Day / night determination (sun below horizon → 0)
#
# Main function:
#   compute_irradiance(lat, lon, timestamp, altitude_m=0)
#       → dict with GHI, DNI, DHI, solar_elevation, solar_azimuth, air_mass,
#         is_day flag, and local solar time.
#
# Inputs  : Station latitude/longitude (deg), UTC datetime, optional altitude.
# Outputs : Irradiance components in W/m² and solar geometry.
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Any

# ── Constants ────────────────────────────────────────────────────────────

SOLAR_CONSTANT = 1361.0  # W/m² (TSI at 1 AU)
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi


# ── Public API ───────────────────────────────────────────────────────────

def compute_irradiance(
    lat: float,
    lon: float,
    timestamp: datetime,
    altitude_m: float = 0.0,
) -> Dict[str, Any]:
    """Compute clear-sky solar irradiance at a ground location.

    Parameters
    ----------
    lat : float
        Station geodetic latitude in degrees (−90 to +90).
    lon : float
        Station geodetic longitude in degrees (−180 to +180).
    timestamp : datetime
        UTC datetime of the observation.
    altitude_m : float, optional
        Station altitude above sea level in metres (default 0).

    Returns
    -------
    dict with keys:
        ghi_w_m2           – Global Horizontal Irradiance (W/m²)
        dni_w_m2           – Direct Normal Irradiance (W/m²)
        dhi_w_m2           – Diffuse Horizontal Irradiance (W/m²)
        solar_elevation_deg – Solar elevation angle (deg, negative = below horizon)
        solar_azimuth_deg  – Solar azimuth angle (deg, 0=N, 90=E, 180=S, 270=W)
        solar_zenith_deg   – Solar zenith angle (deg, 0 = overhead)
        air_mass           – Relative optical air mass (None if sun below horizon)
        is_day             – True if sun above horizon
        local_solar_time_h – Local apparent solar time in hours
        sunrise_utc        – Approximate UTC hour of sunrise (None if polar)
        sunset_utc         – Approximate UTC hour of sunset (None if polar)
        day_length_h       – Day length in hours
        equation_of_time_min – Equation of time in minutes
    """
    utc = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)

    # ── Day of year & fractional year ────────────────────────────────────
    doy = utc.timetuple().tm_yday
    hour_utc = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    gamma = 2.0 * math.pi * (doy - 1 + (hour_utc - 12.0) / 24.0) / 365.0

    # ── Equation of time (Spencer 1971, minutes) ────────────────────────
    eot = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.04089 * math.sin(2 * gamma)
    )

    # ── Solar declination (Spencer 1971, radians) ───────────────────────
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # ── Earth–Sun distance correction factor ────────────────────────────
    eccentricity_corr = (
        1.000110
        + 0.034221 * math.cos(gamma)
        + 0.001280 * math.sin(gamma)
        + 0.000719 * math.cos(2 * gamma)
        + 0.000077 * math.sin(2 * gamma)
    )

    # ── Local apparent solar time ────────────────────────────────────────
    # Time offset in minutes
    time_offset = eot + 4.0 * lon  # lon in degrees → 4 min per degree
    local_solar_time = hour_utc + time_offset / 60.0  # in hours

    # Solar hour angle (degrees): 0 at solar noon, negative before
    hour_angle_deg = (local_solar_time - 12.0) * 15.0
    hour_angle = hour_angle_deg * DEG2RAD

    # ── Solar elevation & azimuth ────────────────────────────────────────
    lat_rad = lat * DEG2RAD
    sin_elev = (
        math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle)
    )
    solar_elevation_rad = math.asin(max(-1.0, min(1.0, sin_elev)))
    solar_elevation_deg = solar_elevation_rad * RAD2DEG
    solar_zenith_deg = 90.0 - solar_elevation_deg

    # Azimuth (measured clockwise from North)
    cos_az_num = (
        math.sin(decl) - math.sin(lat_rad) * sin_elev
    )
    cos_az_den = math.cos(lat_rad) * math.cos(solar_elevation_rad)
    if abs(cos_az_den) > 1e-10:
        cos_az = max(-1.0, min(1.0, cos_az_num / cos_az_den))
        azimuth_deg = math.acos(cos_az) * RAD2DEG
    else:
        azimuth_deg = 180.0  # sun at zenith or horizon singularity
    if hour_angle > 0:
        azimuth_deg = 360.0 - azimuth_deg

    # ── Day length & sunrise/sunset ──────────────────────────────────────
    cos_omega_s = -math.tan(lat_rad) * math.tan(decl)
    if cos_omega_s < -1.0:
        # Midnight sun
        day_length_h = 24.0
        sunrise_utc = 0.0
        sunset_utc = 24.0
    elif cos_omega_s > 1.0:
        # Polar night
        day_length_h = 0.0
        sunrise_utc = None
        sunset_utc = None
    else:
        omega_s = math.acos(cos_omega_s) * RAD2DEG  # half-day angle in degrees
        day_length_h = 2.0 * omega_s / 15.0  # convert degrees to hours
        solar_noon_utc = 12.0 - time_offset / 60.0 + (eot / 60.0)  # approximate
        # Simpler: sunrise/sunset in local solar time
        sunrise_lst = 12.0 - omega_s / 15.0
        sunset_lst = 12.0 + omega_s / 15.0
        sunrise_utc = sunrise_lst - time_offset / 60.0 + hour_utc - local_solar_time
        sunset_utc = sunset_lst - time_offset / 60.0 + hour_utc - local_solar_time
        # Normalise to 0–24
        if sunrise_utc is not None:
            sunrise_utc = sunrise_utc % 24.0
        if sunset_utc is not None:
            sunset_utc = sunset_utc % 24.0

    is_day = solar_elevation_deg > 0.0

    # ── Air mass (Kasten & Young 1989) ───────────────────────────────────
    if is_day and solar_zenith_deg < 90.0:
        zenith_rad = solar_zenith_deg * DEG2RAD
        am = 1.0 / (
            math.cos(zenith_rad)
            + 0.50572 * (96.07995 - solar_zenith_deg) ** (-1.6364)
        )
        # Altitude correction: pressure ratio ≈ exp(-altitude / 8500)
        pressure_ratio = math.exp(-altitude_m / 8500.0)
        am *= pressure_ratio
    else:
        am = None

    # ── Clear-sky irradiance model ───────────────────────────────────────
    if is_day and am is not None and am > 0:
        # Extra-terrestrial irradiance on normal plane
        etr = SOLAR_CONSTANT * eccentricity_corr

        # Linke turbidity factor (typical clear sky = 2.0–3.5)
        linke_tl = 2.5  # reasonable default for clear conditions

        # Ineichen–Perez clear-sky model (simplified broadband)
        # DNI (direct normal irradiance)
        # Using Beer–Lambert with empirical turbidity
        tau_b = 0.09  + 0.04 * (linke_tl - 2.0)  # broadband optical depth
        dni = etr * math.exp(-tau_b * am)

        # Ensure DNI doesn't exceed ETR
        dni = max(0.0, min(dni, etr))

        # DHI (diffuse horizontal) — empirical fraction
        # Typically 10–20% of GHI for clear skies
        diffuse_fraction = 0.10 + 0.04 * (linke_tl - 2.0)
        dhi = etr * diffuse_fraction * math.sin(solar_elevation_rad)
        dhi = max(0.0, dhi)

        # GHI = DNI × sin(elevation) + DHI
        ghi = dni * math.sin(solar_elevation_rad) + dhi
        ghi = max(0.0, ghi)
    else:
        dni = 0.0
        dhi = 0.0
        ghi = 0.0

    return {
        "ghi_w_m2": round(ghi, 2),
        "dni_w_m2": round(dni, 2),
        "dhi_w_m2": round(dhi, 2),
        "solar_elevation_deg": round(solar_elevation_deg, 4),
        "solar_azimuth_deg": round(azimuth_deg, 4),
        "solar_zenith_deg": round(solar_zenith_deg, 4),
        "air_mass": round(am, 4) if am is not None else None,
        "is_day": is_day,
        "local_solar_time_h": round(local_solar_time % 24.0, 4),
        "sunrise_utc_h": round(sunrise_utc, 2) if sunrise_utc is not None else None,
        "sunset_utc_h": round(sunset_utc, 2) if sunset_utc is not None else None,
        "day_length_h": round(day_length_h, 2),
        "equation_of_time_min": round(eot, 2),
        "extraterrestrial_w_m2": round(SOLAR_CONSTANT * eccentricity_corr, 2),
    }


def compute_irradiance_timeline(
    lat: float,
    lon: float,
    epoch: datetime,
    t_offsets_s: list[float],
    altitude_m: float = 0.0,
) -> Dict[str, Any]:
    """Compute irradiance for a sequence of timestamps.

    Parameters
    ----------
    lat, lon : float
        Station coordinates in degrees.
    epoch : datetime
        Reference epoch (UTC).
    t_offsets_s : list[float]
        Time offsets from epoch in seconds.
    altitude_m : float, optional
        Station altitude in metres.

    Returns
    -------
    dict with parallel arrays for each irradiance component.
    """
    results = {
        "ghi_w_m2": [],
        "dni_w_m2": [],
        "dhi_w_m2": [],
        "solar_elevation_deg": [],
        "is_day": [],
        "times_iso": [],
    }

    epoch_utc = epoch.astimezone(timezone.utc) if epoch.tzinfo else epoch.replace(tzinfo=timezone.utc)
    epoch_ts = epoch_utc.timestamp()

    for dt_s in t_offsets_s:
        ts = datetime.fromtimestamp(epoch_ts + dt_s, tz=timezone.utc)
        point = compute_irradiance(lat, lon, ts, altitude_m)
        results["ghi_w_m2"].append(point["ghi_w_m2"])
        results["dni_w_m2"].append(point["dni_w_m2"])
        results["dhi_w_m2"].append(point["dhi_w_m2"])
        results["solar_elevation_deg"].append(point["solar_elevation_deg"])
        results["is_day"].append(point["is_day"])
        results["times_iso"].append(ts.isoformat())

    return results
