# ---------------------------------------------------------------------------
# app/routers/irradiance.py
# ---------------------------------------------------------------------------
# Purpose : API endpoint for solar irradiance at an OGS location.
#           Supports two methods:
#             • "analytical"  – clear-sky model (no external calls)
#             • "open-meteo"  – real/forecast data from Open-Meteo
#
# Endpoints:
#   POST /api/irradiance – compute or fetch solar irradiance for a station
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import IrradianceRequest
from ..services.irradiance_svc import (
    IrradianceParameterError,
    IrradianceProviderError,
    IrradianceQuery,
    IrradianceService,
)

router = APIRouter(prefix="/api", tags=["Irradiance"])

_svc: IrradianceService = IrradianceService()


def set_service(svc: IrradianceService) -> None:
    """Inject service instance from the app factory."""
    global _svc
    _svc = svc


@router.post("/irradiance")
async def get_irradiance(req: IrradianceRequest):
    """Compute or fetch solar irradiance for an OGS location.

    Body parameters:
        lat          – station latitude (deg)
        lon          – station longitude (deg)
        time         – ISO-8601 timestamp (UTC)
        method       – "analytical" or "open-meteo"
        altitude_m   – station altitude in metres (optional, default 0)
    """
    try:
        dt = datetime.fromisoformat(req.time.rstrip("Z"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid ISO timestamp") from exc

    query = IrradianceQuery(
        lat=req.lat,
        lon=req.lon,
        timestamp=dt,
        method=req.method,
        altitude_m=req.altitude_m,
    )

    try:
        result = await run_in_threadpool(_svc.get_irradiance, query)
        return result
    except IrradianceParameterError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IrradianceProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Irradiance error: {exc}") from exc
