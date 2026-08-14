# ---------------------------------------------------------------------------
# app/physics/sky_background.py
# ---------------------------------------------------------------------------
# Purpose : Solar and lunar sky radiance models for background noise in
#           free-space QKD optical links.
#
# Functions:
#   solar_sky_radiance_W_m2_sr_um(solar_zenith_deg, wavelength_nm, sky_scatter_fraction)
#   lunar_sky_radiance_W_m2_sr_um(lat, lon, altitude_m, dt_utc, wavelength_nm)
#   background_noise_from_sky(solar_zenith_deg, lat, lon, altitude_m, dt_utc, wavelength_nm)
#
# Internal helpers (exported for testing):
#   _lunar_V_magnitude(phase_angle_deg)
#   _solar_spectral_irradiance_W_m2_nm(wavelength_nm)
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import astronomy

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lunar_V_magnitude(phase_angle_deg: float) -> float:
    """Compute the visual magnitude of the Moon at a given phase angle.

    Formula (Krisciunas & Schaefer 1991, PASP 103, 1033):
        V_moon = -12.73 + 0.026 * |phase_angle| + 4e-9 * phase_angle^4

    Args:
        phase_angle_deg: Moon phase angle in degrees (0 = full moon, 180 = new moon).

    Returns:
        Visual magnitude V (lower = brighter).
    """
    a = abs(phase_angle_deg)
    return -12.73 + 0.026 * a + 4e-9 * a ** 4


# Solar spectral irradiance anchor at 810 nm [W/m^2/nm] (matches constants.py
# SOLAR_SPECTRAL_IRRAD_810NM; kept local to avoid a cross-module import).
_I_SUN_810_W_M2_NM = 0.48

# Relative AM0 solar spectral irradiance normalised to 1.0 at 810 nm, from the
# ASTM E-490 AM0 reference spectrum.  Captures why daytime QKD prefers longer
# wavelengths: the solar background at 1550 nm is ~1/4 of that at 810 nm.
# Ref: ASTM E-490 (2000); Gruneisen et al., Phys. Rev. Applied 16, 014067 (2021).
_SOLAR_REL_SPECTRUM = (
    (400.0, 1.56),
    (532.0, 1.67),
    (670.0, 1.36),
    (780.0, 1.08),
    (810.0, 1.00),
    (850.0, 0.94),
    (1064.0, 0.55),
    (1310.0, 0.38),
    (1550.0, 0.23),
    (2000.0, 0.10),
)


def _solar_spectral_irradiance_W_m2_nm(wavelength_nm: float) -> float:
    """AM0 solar spectral irradiance at a wavelength [W/m^2/nm].

    Linear interpolation over an ASTM E-490 relative spectrum normalised to the
    810 nm anchor (``_I_SUN_810_W_M2_NM``).  Returning the anchor exactly at
    810 nm preserves backward compatibility with the previous flat model.

    Ref: ASTM E-490 AM0 reference spectrum (2000).
    """
    pts = _SOLAR_REL_SPECTRUM
    if wavelength_nm <= pts[0][0]:
        rel = pts[0][1]
    elif wavelength_nm >= pts[-1][0]:
        rel = pts[-1][1]
    else:
        rel = pts[-1][1]
        for (w0, r0), (w1, r1) in zip(pts, pts[1:]):
            if w0 <= wavelength_nm <= w1:
                frac = (wavelength_nm - w0) / (w1 - w0)
                rel = r0 + frac * (r1 - r0)
                break
    return _I_SUN_810_W_M2_NM * rel


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def solar_sky_radiance_W_m2_sr_um(
    solar_zenith_deg: float,
    wavelength_nm: float = 810.0,
    sky_scatter_fraction: float = 0.1,
) -> float:
    """Daytime sky spectral radiance at the receiver wavelength (scattered sunlight).

    Computes the scattered solar radiance entering the receiver field of view
    using a simplified Lambertian scattering model with clear-sky atmospheric
    extinction.

    Formula (Pirandola et al., Adv. Opt. Photon. 12, 1012 (2020);
             Bedington et al., npj Quantum Inf. 3, 30 (2017)):

        L_sky = I_sun(lambda) * f_scatter * cos(theta_z) * exp(-tau * airmass) / pi

    converted from W/m^2/sr/nm to W/m^2/sr/um (multiply by 1000).

    Args:
        solar_zenith_deg: Solar zenith angle in degrees (0 = sun overhead, 90 = horizon).
        wavelength_nm:    Receiver wavelength in nanometres (default 810 nm).
        sky_scatter_fraction: Fraction of solar spectral irradiance that scatters
                              diffusely into the sky (dimensionless, default 0.1).

    Returns:
        Sky spectral radiance in W / m^2 / sr / um, or 0.0 if sun below horizon.

    Notes:
        - I_sun(810 nm) = 0.48 W/m^2/nm  (ASTM E-490 AM0 solar spectrum).
        - tau = 0.1 (representative clear-sky aerosol optical depth at 810 nm).
        - Airmass model: 1 / max(cos(zenith), 0.1) to avoid divergence near horizon.
    """
    if solar_zenith_deg >= 90.0:
        return 0.0

    # Wavelength-dependent solar spectral irradiance [W/m^2/nm] from the AM0
    # spectrum (spectral-filtering pillar of daytime QKD).  Returns the 810 nm
    # anchor exactly at 810 nm, so legacy behaviour is unchanged.
    I_sun_W_m2_nm = _solar_spectral_irradiance_W_m2_nm(wavelength_nm)

    # Clear-sky optical depth at 810 nm (aerosol + Rayleigh, representative value)
    tau = 0.1

    zenith_rad = math.radians(solar_zenith_deg)
    cos_zenith = math.cos(zenith_rad)

    # Air mass: Chapman/Kasten approximation (clamped to avoid singularity)
    airmass = 1.0 / max(cos_zenith, 0.1)

    # Scattered sky radiance [W/m^2/sr/nm]
    L_sky_per_nm = (
        I_sun_W_m2_nm
        * sky_scatter_fraction
        * cos_zenith
        * math.exp(-tau * airmass)
        / math.pi
    )

    # Convert nm -> um (multiply by 1000)
    return L_sky_per_nm * 1000.0


def lunar_sky_radiance_W_m2_sr_um(
    lat: float,
    lon: float,
    altitude_m: float,
    dt_utc: datetime,
    wavelength_nm: float = 810.0,
) -> float:
    """Nighttime sky spectral radiance from scattered moonlight.

    Uses astronomy-engine for Moon phase angle and elevation, then applies the
    Krisciunas-Schaefer empirical model to estimate the sky radiance at the
    receiver wavelength.

    Formula (Krisciunas & Schaefer 1991, PASP 103, 1033):
        V_moon  = -12.73 + 0.026 * |phase_angle| + 4e-9 * phase_angle^4
        E_lux   = 10^((-14.18 - V_moon) / 2.5)   [lux at ground]
        A_scat  = 0.10 * sin(max(moon_altitude_deg, 1 deg))
        H_lunar = E_lux * A_scat / pi * lux_to_W_m2 * spectral_scale

    where:
        lux_to_W_m2   = 1.464e-3  (photometric-to-radiometric at 555 nm)
        spectral_scale = 0.85 / 1e3  (relative Moon SED factor, per nm -> per um)

    Args:
        lat:         Observer geodetic latitude (degrees).
        lon:         Observer geodetic longitude (degrees).
        altitude_m:  Observer altitude above sea level (metres).
        dt_utc:      UTC datetime of the observation (timezone-aware).
        wavelength_nm: Receiver wavelength in nm (default 810 nm, currently unused
                       but retained for future spectral scaling).

    Returns:
        Lunar sky spectral radiance in W / m^2 / sr / um, or 0.0 if Moon is
        below horizon or phase angle > 168 deg (near-new-moon threshold).

    Note:
        astronomy.Time.Make expects (year, month, day, hour, minute, second).
        astronomy.Equator returns equatorial coordinates; astronomy.Horizon
        converts them to altitude/azimuth for the given observer.
    """
    # Ensure UTC
    if dt_utc is None:
        return 0.0
    utc = dt_utc.astimezone(timezone.utc) if dt_utc.tzinfo else dt_utc.replace(tzinfo=timezone.utc)

    # Build astronomy-engine time and observer objects
    t = astronomy.Time.Make(
        utc.year, utc.month, utc.day,
        utc.hour, utc.minute, float(utc.second + utc.microsecond * 1e-6),
    )
    observer = astronomy.Observer(lat, lon, altitude_m)

    # Moon illumination (phase angle)
    illum = astronomy.Illumination(astronomy.Body.Moon, t)
    phase_angle_deg = illum.phase_angle

    # Near-new-moon threshold: negligible illumination
    if phase_angle_deg > 168.0:
        return 0.0

    # Moon horizon coordinates via equatorial coordinates
    moon_eq = astronomy.Equator(astronomy.Body.Moon, t, observer, True, True)
    horiz = astronomy.Horizon(t, observer, moon_eq.ra, moon_eq.dec, astronomy.Refraction.Normal)
    moon_altitude_deg = horiz.altitude

    # Moon below horizon
    if moon_altitude_deg <= 0.0:
        return 0.0

    # Krisciunas & Schaefer (1991) sky brightness model
    V_moon = _lunar_V_magnitude(phase_angle_deg)

    # Illuminance at ground level from the Moon [lux]
    E_lux = 10.0 ** ((-14.18 - V_moon) / 2.5)

    # Scattering into receiver solid angle (elevation-dependent)
    A_scatter = 0.10 * math.sin(math.radians(max(moon_altitude_deg, 1.0)))

    # Convert lux to W/m^2 (photometric at 555 nm) and scale to 810 nm per um
    lux_to_W_m2 = 1.464e-3       # W/m^2 per lux (at 555 nm peak)
    spectral_scale = 0.85 / 1e3  # relative Moon spectrum at 810 nm / 555 nm, nm -> um

    H_lunar = E_lux * A_scatter / math.pi * lux_to_W_m2 * spectral_scale

    return H_lunar


def background_noise_from_sky(
    solar_zenith_deg: float,
    lat: float,
    lon: float,
    altitude_m: float,
    dt_utc: Optional[datetime],
    wavelength_nm: float = 810.0,
) -> float:
    """Total sky spectral radiance for background noise computation.

    Single entry point combining solar (daytime) and lunar (nighttime) sky
    radiance models.  The result feeds directly into background_noise_cps()
    in link_budget.py as the H_rad_W_m2_sr_um parameter.

    Logic:
        - solar_zenith_deg < 90:  daytime; solar sky dominates, lunar is negligible.
        - solar_zenith_deg >= 90: nighttime; use lunar model only.

    Args:
        solar_zenith_deg: Solar zenith angle in degrees.
        lat:              Observer latitude (degrees).
        lon:              Observer longitude (degrees).
        altitude_m:       Observer altitude above sea level (metres).
        dt_utc:           UTC datetime (timezone-aware); required for nighttime.
        wavelength_nm:    Receiver wavelength in nm (default 810 nm).

    Returns:
        Sky spectral radiance in W / m^2 / sr / um.
    """
    if solar_zenith_deg < 90.0:
        return solar_sky_radiance_W_m2_sr_um(solar_zenith_deg, wavelength_nm)
    else:
        return lunar_sky_radiance_W_m2_sr_um(lat, lon, altitude_m, dt_utc, wavelength_nm)
