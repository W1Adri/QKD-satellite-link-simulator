# ---------------------------------------------------------------------------
# app/routers/pcflos.py
# ---------------------------------------------------------------------------
# Purpose : POST /api/pcflos — compute PCFLOS monthly statistics for a
#           ground station location from Open-Meteo ERA5 historical cloud
#           cover data.
#
# Endpoints:
#   POST /api/pcflos  – returns monthly_pcflos, annual_pcflos, year,
#                       threshold_pct, and optional station_name
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import PCFLOSRequest
from ..services.pcflos_svc import compute_pcflos, PCFLOSError

router = APIRouter(prefix="/api", tags=["PCFLOS"])
logger = logging.getLogger(__name__)


@router.post("/pcflos")
async def pcflos(req: PCFLOSRequest):
    """Compute PCFLOS monthly statistics for a ground station location.

    Fetches 1 year of hourly ERA5 cloud_cover from the Open-Meteo archive and
    reduces it with BOTH estimators, so the two are always comparable:

      * ``monthly_expectation`` — mean over hours of (1 − N)^f(ε), the
        Kauth & Penquite (1967) shape-factor model at the requested elevation.
        No free threshold; equals 1 − <N> at zenith.
      * ``monthly_threshold`` — the legacy P(cover < threshold_pct) count.

    ``monthly_pcflos`` / ``annual_pcflos`` mirror whichever ``estimator`` was
    requested, so existing consumers keep working.

    Returns 502 if the upstream archive API is unavailable.
    """
    try:
        result = await run_in_threadpool(
            lambda: compute_pcflos(
                req.lat, req.lon, req.year, req.threshold_pct,
                estimator=req.estimator, elev_deg=req.elev_deg,
                beta=req.beta, night_only=req.night_only,
            )
        )
        if req.station_name:
            result["station_name"] = req.station_name
        return result
    except PCFLOSError as exc:
        raise HTTPException(502, f"Cloud cover data unavailable: {exc}") from exc
    except Exception as exc:
        logger.exception("PCFLOS computation error")
        raise HTTPException(500, f"PCFLOS computation error: {exc}") from exc
