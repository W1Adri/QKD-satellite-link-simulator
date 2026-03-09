# ---------------------------------------------------------------------------
# app/physics/geometry.py
# ---------------------------------------------------------------------------
# Purpose : Line-of-sight (LOS) geometry between a ground station and a
#           satellite, including elevation, azimuth, slant range, Doppler
#           shift, and diffraction-limited geometric link loss.
#
# Functions:
#   enu_matrix(lat, lon)              – East-North-Up rotation matrix
#   los_elevation(station, r_ecef)    – elevation / azimuth / distance
#   doppler_factor(station, r, v, λ)  – relativistic Doppler ratio
#   geometric_loss(dist, D_sat, D_gnd, λ)  – free-space diffraction loss (dB)
#   compute_station_metrics(pts, sta, optics, atmo)
#                                     – vectorised metrics over a timeline
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .constants import (
    C_LIGHT_KMS,
    DEG2RAD,
    EARTH_RADIUS_KM,
    RAD2DEG,
)
from .link_budget import (
    atm_loss_db,
    background_noise_cps,
    coupling_from_loss,
    is_eclipsed,
    pointing_loss_db,
    received_power_dbm,
    link_margin_db,
    scintillation_loss_db,
    sun_core_angle_deg,
    total_link_loss_db,
)
from .propagation import ecef_from_latlon
from .solar import sun_direction_eci, _parse_iso, _to_astro_time


# ── ENU helpers ──────────────────────────────────────────────────────────

def _enu_matrix(lat_deg: float, lon_deg: float) -> List[List[float]]:
    lat = lat_deg * DEG2RAD
    lon = lon_deg * DEG2RAD
    sl, cl = math.sin(lat), math.cos(lat)
    so, co = math.sin(lon), math.cos(lon)
    return [
        [-so, co, 0],
        [-sl * co, -sl * so, cl],
        [cl * co, cl * so, sl],
    ]


# ── Line-of-Sight ───────────────────────────────────────────────────────

def los_elevation(
    station: Dict[str, float],
    r_ecef: List[float],
) -> Dict[str, float]:
    """Compute slant range, elevation and azimuth from *station* to satellite.

    Args:
        station: dict with keys ``lat``, ``lon`` (degrees) and optional
            ``altitude_m`` (metres above sea level, default 0).
        r_ecef: satellite ECEF position [km].

    Returns:
        ``{distanceKm, elevationDeg, azimuthDeg}``
    """
    alt_km = station.get("altitude_m", 0.0) / 1000.0
    s_ecef = ecef_from_latlon(station["lat"], station["lon"],
                              radius_km=EARTH_RADIUS_KM + alt_km)
    rel = [r_ecef[i] - s_ecef[i] for i in range(3)]
    M = _enu_matrix(station["lat"], station["lon"])
    enu = [
        sum(M[r][c] * rel[c] for c in range(3))
        for r in range(3)
    ]
    dist = math.sqrt(sum(c * c for c in rel))
    elev = math.atan2(enu[2], math.sqrt(enu[0] ** 2 + enu[1] ** 2))
    az = math.atan2(enu[0], enu[1])
    return {
        "distanceKm": dist,
        "elevationDeg": elev * RAD2DEG,
        "azimuthDeg": (az * RAD2DEG + 360) % 360,
    }


# ── Doppler ──────────────────────────────────────────────────────────────

def doppler_factor(
    station: Dict[str, float],
    r_ecef: List[float],
    v_ecef: List[float],
    wavelength_nm: float,
) -> Dict[str, float]:
    """First-order Doppler factor and observed wavelength.

    Returns:
        ``{factor, observedWavelength}``
    """
    alt_km = station.get("altitude_m", 0.0) / 1000.0
    s_ecef = ecef_from_latlon(station["lat"], station["lon"],
                              radius_km=EARTH_RADIUS_KM + alt_km)
    rel = [r_ecef[i] - s_ecef[i] for i in range(3)]
    dist = math.sqrt(sum(c * c for c in rel))
    unit = [c / dist for c in rel]
    vr = sum(v_ecef[i] * unit[i] for i in range(3))
    f = 1.0 / (1.0 - vr / C_LIGHT_KMS)
    lam = wavelength_nm * 1e-9  # m
    return {"factor": f, "observedWavelength": lam * f}


# ── Geometric link loss ─────────────────────────────────────────────────

def geometric_loss(
    distance_km: float,
    sat_aperture_m: float,
    ground_aperture_m: float,
    wavelength_nm: float,
) -> Dict[str, float]:
    """Diffraction-limited free-space coupling loss.

    Returns:
        ``{coupling, lossDb}``
    """
    lam = wavelength_nm * 1e-9
    dist_m = distance_km * 1000.0
    divergence = 1.22 * lam / max(sat_aperture_m, 1e-3)
    spot_r = max(divergence * dist_m * 0.5, 1e-6)
    capture_r = ground_aperture_m * 0.5
    coupling = min(1.0, (capture_r / spot_r) ** 2)
    loss_db = -10.0 * math.log10(max(coupling, 1e-9))
    return {"coupling": coupling, "lossDb": loss_db}


# ── Atmosphere zenith-scaling ────────────────────────────────────────────

def _scale_atmosphere(
    elev_deg: float,
    r0_z: float,
    fG_z: float,
    theta0_z: float,
    wind_rms: float,
    aod_db: float,
    abs_db: float,
) -> Dict[str, float]:
    """Scale zenith atmospheric parameters by air-mass at *elev_deg*."""
    if elev_deg <= 0:
        return {"r0": 0, "fG": 0, "theta0": 0,
                "wind": wind_rms, "aod": 0, "abs": 0}
    zen_rad = (90.0 - elev_deg) * DEG2RAD
    cz = max(math.cos(zen_rad), 1e-6)
    am = 1.0 / cz
    return {
        "r0": r0_z * cz ** (3.0 / 5.0),
        "fG": fG_z * cz ** (-9.0 / 5.0),
        "theta0": theta0_z * cz ** (8.0 / 5.0),
        "wind": wind_rms,
        "aod": aod_db * am,
        "abs": abs_db * am,
    }


# ── Vectorised station metrics ──────────────────────────────────────────

def _ecef_to_eci(r_ecef: List[float], gmst: float) -> List[float]:
    """Rotate ECEF position to ECI given GMST (radians)."""
    c = math.cos(gmst)
    s = math.sin(gmst)
    return [c * r_ecef[0] - s * r_ecef[1],
            s * r_ecef[0] + c * r_ecef[1],
            r_ecef[2]]


def compute_station_metrics(
    data_points: List[Dict[str, Any]],
    station: Dict[str, float],
    optics: Dict[str, float],
    atmosphere: Optional[Dict[str, float]] = None,
    *,
    link_budget_cfg: Optional[Dict[str, Any]] = None,
    cn2_layers: Optional[List] = None,
    link_direction: str = "downlink",
    epoch_iso: Optional[str] = None,
) -> Dict[str, List[float]]:
    """Compute link metrics for every point in a propagated timeline.

    Args:
        data_points: list from ``propagate_orbit`` output.
        station: ``{lat, lon}`` in degrees.
        optics: ``{satAperture, groundAperture, wavelength}`` (m / m / nm).
        atmosphere: optional zenith summary dict.
        link_budget_cfg: optional dict with keys
            pointing_error_urad, atm_zenith_aod_db, atm_zenith_abs_db,
            fixed_optics_loss_db, scintillation_enabled, scintillation_p0,
            background_enabled, background_Hrad_W_m2_sr_um,
            background_fov_mrad, background_delta_lambda_nm,
            sun_exclusion_deg, tx_power_dbm, rx_sensitivity_dbm.
        cn2_layers: optional list of (altitude_m, Cn2) tuples for
            scintillation computation.
        link_direction: ``"downlink"`` (plane wave) or ``"uplink"``
            (spherical wave).
        epoch_iso: ISO-8601 epoch string (needed for sun/eclipse
            computation).

    Returns:
        Dict of parallel arrays.  Original keys preserved; new keys:
        geoLossDb, atmLossDb, pointingLossDb, scintLossDb, fixedLossDb,
        totalLossDb (alias of lossDb), couplingTotal, backgroundCps,
        sunCoreAngleDeg, eclipsed, sunExcluded, rxPowerDbm,
        linkMarginDb, linkEstablished.
    """
    atmo = atmosphere or {}
    r0_z = atmo.get("r0_zenith", 0.1)
    fG_z = atmo.get("fG_zenith", 30.0)
    th0_z = atmo.get("theta0_zenith", 1.5)
    w_rms = atmo.get("wind_rms", 15.0)
    aod_z = atmo.get("loss_aod_db", 0.0)
    abs_z = atmo.get("loss_abs_db", 0.0)

    # Link-budget config (defaults → backward-compatible)
    lb = link_budget_cfg or {}
    pe_urad = lb.get("pointing_error_urad", 0.0)
    atm_aod = lb.get("atm_zenith_aod_db", 0.0)
    atm_abs = lb.get("atm_zenith_abs_db", 0.0)
    fixed_db = lb.get("fixed_optics_loss_db", 0.0)
    scint_on = lb.get("scintillation_enabled", False)
    scint_p0 = lb.get("scintillation_p0", 0.01)
    bg_on = lb.get("background_enabled", False)
    bg_hrad = lb.get("background_Hrad_W_m2_sr_um", 0.0)
    bg_fov = lb.get("background_fov_mrad", 0.0)
    bg_dlam = lb.get("background_delta_lambda_nm", 0.0)

    # Sun / eclipse config
    sun_excl_deg = lb.get("sun_exclusion_deg", 0.0)

    # Received power / link margin config
    tx_pwr_dbm = lb.get("tx_power_dbm", None)
    rx_sens_dbm = lb.get("rx_sensitivity_dbm", None)

    is_uplink = (link_direction or "").strip().lower() == "uplink"

    wl_nm = optics.get("wavelength", 810)
    sat_ap = optics.get("satAperture", 0.6)
    gnd_ap = optics.get("groundAperture", 1.0)

    # Station altitude above sea level (metres)
    station_alt_m = station.get("altitude_m", 0.0) if station else 0.0

    # For uplink: transmitter = ground, receiver = satellite
    # For downlink: transmitter = satellite, receiver = ground
    tx_ap = gnd_ap if is_uplink else sat_ap
    rx_ap = sat_ap if is_uplink else gnd_ap

    # Divergence for pointing loss (uses transmitter aperture)
    lam_m = wl_nm * 1e-9
    divergence_rad = 1.22 * lam_m / max(tx_ap, 1e-3)

    out: Dict[str, List[float]] = {
        "distanceKm": [], "elevationDeg": [], "lossDb": [],
        "doppler": [], "azimuthDeg": [],
        "r0": [], "fG": [], "theta0": [],
        "wind": [], "aod": [], "abs": [],
        # link-budget component arrays
        "geoLossDb": [], "atmLossDb": [], "pointingLossDb": [],
        "scintLossDb": [], "fixedLossDb": [], "totalLossDb": [],
        "couplingTotal": [], "backgroundCps": [],
        # sun / eclipse arrays
        "sunCoreAngleDeg": [], "eclipsed": [], "sunExcluded": [],
        # received power / link margin
        "rxPowerDbm": [], "linkMarginDb": [], "linkEstablished": [],
    }

    if not station or not data_points:
        return out

    # Parse epoch once for sun/eclipse computation
    epoch_dt = None
    if epoch_iso:
        try:
            epoch_dt = _parse_iso(epoch_iso)
        except Exception:
            pass  # sun/eclipse will be skipped

    for pt in data_points:
        los = los_elevation(station, pt["r_ecef"])

        # Geometric loss uses tx/rx apertures based on link direction
        gl = geometric_loss(los["distanceKm"], tx_ap, rx_ap, wl_nm)
        dop = doppler_factor(
            station, pt["r_ecef"], pt["v_ecef"], wl_nm,
        )
        atm = _scale_atmosphere(
            los["elevationDeg"], r0_z, fG_z, th0_z, w_rms, aod_z, abs_z,
        )

        elev = los["elevationDeg"]

        # Satellite altitude from ECEF position (for uplink Rytov kernel)
        r_ecef = pt["r_ecef"]
        sat_alt_m = (
            math.sqrt(sum(c * c for c in r_ecef)) - EARTH_RADIUS_KM
        ) * 1000.0

        # ── link-budget components ──
        geo_db = gl["lossDb"]
        a_db = atm_loss_db(elev, atm_aod, atm_abs)
        p_db = pointing_loss_db(pe_urad, divergence_rad)
        s_db = (
            scintillation_loss_db(
                elev, wl_nm, rx_ap, cn2_layers, scint_p0,
                link_direction=link_direction,
                H_sat_m=sat_alt_m,
                h_gs=station_alt_m,
            )
            if scint_on else 0.0
        )
        f_db = fixed_db if elev > 0 else 0.0

        t_db = total_link_loss_db(geo_db, a_db, p_db, s_db, f_db)
        coup = coupling_from_loss(t_db)

        bg_cps = (
            background_noise_cps(bg_hrad, bg_fov, rx_ap, bg_dlam, wl_nm)
            if bg_on and elev > 0 else 0.0
        )

        # ── sun / eclipse ──
        sun_angle = 180.0
        ecl = False
        sun_excl = False
        if epoch_dt is not None:
            from datetime import datetime, timezone
            t_s = pt.get("t", 0.0)
            dt_obj = datetime.fromtimestamp(
                epoch_dt.timestamp() + t_s, tz=timezone.utc,
            )
            astro_t = _to_astro_time(dt_obj)
            sun_dir = sun_direction_eci(astro_t)

            # Satellite ECI position (from data_point or convert from ECEF)
            sat_eci = pt.get("r_eci")
            if sat_eci is None:
                gmst = pt.get("gmst", 0.0)
                sat_eci = _ecef_to_eci(r_ecef, gmst)

            # Station ECI position
            gmst = pt.get("gmst", 0.0)
            alt_km = station.get("altitude_m", 0.0) / 1000.0
            sta_ecef = ecef_from_latlon(
                station["lat"], station["lon"],
                radius_km=EARTH_RADIUS_KM + alt_km,
            )
            sta_eci = _ecef_to_eci(sta_ecef, gmst)

            sun_angle = sun_core_angle_deg(sat_eci, sta_eci, list(sun_dir))
            ecl = is_eclipsed(sat_eci, list(sun_dir))
            if sun_excl_deg > 0 and sun_angle < sun_excl_deg:
                sun_excl = True

        # ── received power / link margin ──
        rx_pwr = None
        margin = None
        link_ok = True
        if tx_pwr_dbm is not None:
            rx_pwr = received_power_dbm(tx_pwr_dbm, t_db)
            if rx_sens_dbm is not None:
                margin = link_margin_db(rx_pwr, rx_sens_dbm)
                link_ok = margin >= 0 and elev > 0
            else:
                link_ok = elev > 0
        else:
            link_ok = elev > 0

        # ── append ──
        out["distanceKm"].append(los["distanceKm"])
        out["elevationDeg"].append(elev)
        out["lossDb"].append(t_db)  # backward compat: total
        out["doppler"].append(dop["factor"])
        out["azimuthDeg"].append(los["azimuthDeg"])
        out["r0"].append(atm["r0"])
        out["fG"].append(atm["fG"])
        out["theta0"].append(atm["theta0"])
        out["wind"].append(atm["wind"])
        out["aod"].append(atm["aod"])
        out["abs"].append(atm["abs"])

        out["geoLossDb"].append(geo_db)
        out["atmLossDb"].append(a_db)
        out["pointingLossDb"].append(p_db)
        out["scintLossDb"].append(s_db)
        out["fixedLossDb"].append(f_db)
        out["totalLossDb"].append(t_db)
        out["couplingTotal"].append(coup)
        out["backgroundCps"].append(bg_cps)

        out["sunCoreAngleDeg"].append(sun_angle)
        out["eclipsed"].append(ecl)
        out["sunExcluded"].append(sun_excl)
        out["rxPowerDbm"].append(rx_pwr)
        out["linkMarginDb"].append(margin)
        out["linkEstablished"].append(link_ok)

    return out
