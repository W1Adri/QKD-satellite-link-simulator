# ---------------------------------------------------------------------------
# app/routers/atmosphere.py
# ---------------------------------------------------------------------------
# Purpose : API endpoints for atmospheric Cn² profile queries and gridded
#           weather-field sampling.
#
# Endpoints:
#   POST /api/get_atmosphere_profile – build Cn² profile for lat/lon/time
#   POST /api/get_weather_field      – grid-sample a weather variable
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import AtmosRequest, WeatherFieldRequest
from ..services.atmosphere_svc import (
    AtmosphereModelNotFoundError,
    AtmosphereProviderError,
    AtmosphereQuery,
    AtmosphereService,
)
from ..services.weather_svc import (
    WeatherFieldParameterError,
    WeatherFieldQuery,
    WeatherFieldService,
)

router = APIRouter(prefix="/api", tags=["Atmosphere"])

_atmo: AtmosphereService = AtmosphereService()
_weather: WeatherFieldService = WeatherFieldService()


def set_services(atmo: AtmosphereService, weather: WeatherFieldService) -> None:
    """Inject service instances created by the app factory."""
    global _atmo, _weather
    _atmo = atmo
    _weather = weather


@router.post("/get_atmosphere_profile")
async def get_atmosphere_profile(req: AtmosRequest):
    try:
        dt = datetime.fromisoformat(req.time.rstrip("Z"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid ISO timestamp") from exc
    wl = req.wavelength_nm or 810.0
    q = AtmosphereQuery(
        lat=req.lat, lon=req.lon, timestamp=dt,
        model=req.model,
        ground_cn2_day=req.ground_cn2_day,
        ground_cn2_night=req.ground_cn2_night,
        wavelength_nm=wl,
    )
    try:
        return await run_in_threadpool(_atmo.build_profile, q)
    except AtmosphereModelNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except AtmosphereProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Atmosphere error: {exc}") from exc


@router.post("/get_weather_field")
async def get_weather_field(req: WeatherFieldRequest):
    try:
        dt = datetime.fromisoformat(req.time.rstrip("Z"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid ISO timestamp") from exc
    q = WeatherFieldQuery(
        timestamp=dt, variable=req.variable,
        level_hpa=req.level_hpa, samples=req.samples,
    )
    try:
        return await run_in_threadpool(_weather.build_field, q)
    except WeatherFieldParameterError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AtmosphereProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Weather error: {exc}") from exc
