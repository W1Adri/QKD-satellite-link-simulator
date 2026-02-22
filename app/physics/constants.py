# ---------------------------------------------------------------------------
# app/physics/constants.py
# ---------------------------------------------------------------------------
# Purpose : Single source of truth for every physical / orbital constant used
#           across the backend.  Import from here instead of duplicating magic
#           numbers in individual modules.
#
# Main symbols:
#   MU_EARTH           – standard gravitational parameter  (km³/s²)
#   EARTH_RADIUS_KM    – equatorial radius                 (km)
#   EARTH_ROT_RATE     – rotation rate                     (rad/s)
#   J2, J3, J4         – zonal harmonic coefficients
#   SIDEREAL_DAY       – sidereal day length               (s)
#   DEG2RAD / RAD2DEG  – angular conversion factors
#   C_LIGHT            – speed of light                    (km/s  & m/s)
#   H_PLANCK           – Planck constant                   (J·s)
#   SOLAR_MEAN_MOTION  – ≈0.9856 °/day
# ---------------------------------------------------------------------------
from __future__ import annotations

import math

# --- Astronomical / Earth constants ---
MU_EARTH: float = 398_600.4418          # km³/s²
EARTH_RADIUS_KM: float = 6378.137      # equatorial, km
EARTH_ROT_RATE: float = 7.2921150e-5   # rad/s
J2: float = 1.08263e-3
J3: float = -2.53881e-6
J4: float = -1.65597e-6
SIDEREAL_DAY: float = 86_164.0905      # seconds

# --- Angular helpers ---
DEG2RAD: float = math.pi / 180.0
RAD2DEG: float = 180.0 / math.pi

# --- Optical / QKD constants ---
C_LIGHT_KMS: float = 299_792.458       # km/s
C_LIGHT_MS: float = 2.99792458e8       # m/s
H_PLANCK: float = 6.62607015e-34       # J·s

# --- Solar ---
SOLAR_MEAN_MOTION: float = 360.0 / 365.2421897   # °/day

# --- Orbit feasibility limits ---
MIN_ALTITUDE_KM: float = 160.0
GEO_ALTITUDE_KM: float = 35_786.0
MIN_SEMI_MAJOR: float = EARTH_RADIUS_KM + MIN_ALTITUDE_KM
MAX_SEMI_MAJOR: float = EARTH_RADIUS_KM + GEO_ALTITUDE_KM
