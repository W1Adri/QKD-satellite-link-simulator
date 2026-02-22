# ---------------------------------------------------------------------------
# app/routers/constellation.py
# ---------------------------------------------------------------------------
# Purpose : Constellation analysis, propagation and coverage endpoints.
#           Delegates heavy work to app.constellation_manager via threadpool.
#
# Endpoints:
#   POST /api/constellation/analyze                  – analyse from TLE
#   POST /api/constellation/propagate                – propagate over time
#   GET  /api/constellation/{id}/coverage            – ground-point coverage
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/constellation", tags=["Constellation"])


def _manager():
    """Lazy import of the constellation manager singleton."""
    from .. import constellation_manager
    return constellation_manager.get_constellation_manager()


# ── Analyse ──────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_constellation(payload: Dict[str, Any]):
    constellation_id = payload.get("constellation_id", "temp")
    tle_list = payload.get("tles", [])
    if not tle_list:
        raise HTTPException(400, "No TLE data provided")

    mgr = _manager()
    count = await run_in_threadpool(
        mgr.add_constellation_from_tle, constellation_id, tle_list
    )
    if count == 0:
        raise HTTPException(400, "No valid TLE data parsed")

    analysis = await run_in_threadpool(mgr.analyze_constellation, constellation_id)
    if not analysis:
        raise HTTPException(500, "Failed to analyze constellation")

    return {
        "constellation_id": constellation_id,
        "parsed_satellites": count,
        "analysis": {
            "total_satellites": analysis.total_satellites,
            "operational_satellites": analysis.operational_satellites,
            "planes": analysis.planes,
            "mean_altitude_km": analysis.mean_altitude_km,
            "altitude_range_km": analysis.altitude_range_km,
            "mean_inclination_deg": analysis.mean_inclination_deg,
            "inclination_range_deg": analysis.inclination_range_deg,
            "metadata": analysis.metadata,
        },
    }


# ── Propagate ────────────────────────────────────────────────────────────

@router.post("/propagate")
async def propagate_constellation(payload: Dict[str, Any]):
    constellation_id = payload.get("constellation_id")
    if not constellation_id:
        raise HTTPException(400, "constellation_id required")

    start_str = payload.get("start_time")
    try:
        start = (
            datetime.fromisoformat(start_str.rstrip("Z")) if start_str
            else datetime.utcnow()
        )
    except ValueError as exc:
        raise HTTPException(400, f"Invalid start_time: {exc}") from exc

    duration = payload.get("duration_seconds", 3600)
    step = payload.get("time_step_seconds", 60)

    mgr = _manager()
    results = await run_in_threadpool(
        mgr.propagate_constellation, constellation_id, start, duration, step
    )

    output: Dict[str, list] = {}
    for sat_name, states in results.items():
        output[sat_name] = [
            {
                "timestamp": s.timestamp.isoformat() + "Z",
                "latitude": s.latitude,
                "longitude": s.longitude,
                "altitude": s.altitude,
            }
            for s in states
        ]

    first_val = next(iter(output.values()), [])
    return {
        "constellation_id": constellation_id,
        "satellites": len(output),
        "samples_per_satellite": len(first_val),
        "data": output,
    }


# ── Coverage ─────────────────────────────────────────────────────────────

@router.get("/{constellation_id}/coverage")
async def compute_coverage(
    constellation_id: str,
    lat: float = Query(...),
    lon: float = Query(...),
    duration_seconds: float = Query(86400),
):
    mgr = _manager()
    coverage = await run_in_threadpool(
        mgr.compute_coverage_at_location,
        constellation_id,
        lat,
        lon,
        datetime.utcnow(),
        duration_seconds,
    )
    return coverage
