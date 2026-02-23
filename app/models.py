# ---------------------------------------------------------------------------
# app/models.py
# ---------------------------------------------------------------------------
# Purpose : Pydantic schemas shared across routers for request validation
#           and response serialisation.
#
# Classes (request):
#   OGSLocation, UserCreate, ChatCreate, AtmosRequest,
#   WeatherFieldRequest, SolveRequest
#
# Classes (response):
#   UserRead, AuthResponse, ChatRead, UserCount
#
# Helpers:
#   is_in_europe_bbox(lat, lon) – bounding-box guard
#   normalize_username(value)   – lowercase & strip
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── OGS ──────────────────────────────────────────────────────────────────

class OGSLocation(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1)
    lat: float
    lon: float
    aperture_m: float = Field(default=1.0, ge=0.1, le=15.0)
    notes: Optional[str] = None


# ── Users / Chat ─────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=4, max_length=128)


class UserRead(BaseModel):
    id: int
    username: str
    created_at: str


class AuthResponse(UserRead):
    message: str


class ChatCreate(BaseModel):
    user_id: int
    message: str = Field(min_length=1, max_length=2000)


class ChatRead(BaseModel):
    id: int
    user_id: int
    username: str
    message: str
    created_at: str


class UserCount(BaseModel):
    count: int


# ── Atmosphere ───────────────────────────────────────────────────────────

class AtmosRequest(BaseModel):
    lat: float
    lon: float
    time: str
    ground_cn2_day: float
    ground_cn2_night: float
    model: str = Field(default="hufnagel-valley")
    wavelength_nm: Optional[float] = Field(default=810.0, ge=400.0, le=2000.0)


class IrradianceRequest(BaseModel):
    """Request payload for POST /api/irradiance."""
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    time: str
    method: str = Field(default="analytical")   # "analytical" | "open-meteo"
    altitude_m: float = Field(default=0.0, ge=0.0, le=9000.0)


class WeatherFieldRequest(BaseModel):
    time: str
    variable: str = Field(default="wind_speed")
    level_hpa: int = Field(default=200, ge=50, le=1000)
    samples: int = Field(default=120, ge=16, le=900)


# ── Unified solver ───────────────────────────────────────────────────────

class SolveRequest(BaseModel):
    """Payload for POST /api/solve."""
    # Orbit mode: "elements" or "tle"
    mode: str = Field(default="elements")

    # Keplerian elements (used when mode == "elements")
    semi_major_axis: float = Field(default=6771.0)
    eccentricity: float = Field(default=0.001, ge=0.0, lt=1.0)
    inclination_deg: float = Field(default=53.0, ge=0.0, le=180.0)
    raan_deg: float = Field(default=0.0)
    arg_perigee_deg: float = Field(default=0.0)
    mean_anomaly_deg: float = Field(default=0.0)
    j2_enabled: bool = True
    epoch: Optional[str] = None

    # Station
    station_lat: Optional[float] = None
    station_lon: Optional[float] = None

    # Optics
    sat_aperture_m: float = Field(default=0.6, ge=0.05, le=5.0)
    ground_aperture_m: float = Field(default=1.0, ge=0.05, le=15.0)
    wavelength_nm: float = Field(default=810.0, ge=400.0, le=2000.0)

    # Time
    samples_per_orbit: int = Field(default=180, ge=10, le=1000)
    total_orbits: int = Field(default=3, ge=1, le=50)

    # Atmosphere (optional)
    atmosphere_model: Optional[str] = None
    ground_cn2_day: float = 5e-14
    ground_cn2_night: float = 5e-15

    # QKD (optional)
    qkd_protocol: Optional[str] = None
    photon_rate: float = 1e9
    detector_efficiency: float = 0.25
    dark_count_rate: float = 100.0

    # Walker constellation (optional)
    walker_T: Optional[int] = None
    walker_P: Optional[int] = None
    walker_F: Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────────────

def is_in_europe_bbox(lat: float, lon: float) -> bool:
    return (25.0 <= lat <= 72.0) and (-31.0 <= lon <= 45.0)


def normalize_username(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid username")
    return value.strip().lower()
