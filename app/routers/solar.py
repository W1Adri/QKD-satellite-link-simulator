# ---------------------------------------------------------------------------
# app/routers/solar.py
# ---------------------------------------------------------------------------
# Purpose : REST endpoint for solar ephemeris data.  Receives a time range
#           (epoch + offsets) and returns the Sun direction in ECI, GMST
#           angles, and sub-solar points needed by the 3D frontend.
#
# Endpoints:
#   POST /api/solar  →  SolarResponse
#
# Input  : SolarRequest  (epoch_iso, t_offsets_s)
# Output : SolarResponse (sun_dir_eci[], gmst_rad[], subsolar_lat_lon[])
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import List

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..physics.solar import compute_solar_ephemeris, compute_scene_timeline

router = APIRouter(prefix="/api", tags=["solar"])

# ── LRU-style cache (single-entry) ─────────────────────────────────────────
_cache_key: str | None = None
_cache_val: dict | None = None


def _make_cache_key(req: "SolarRequest") -> str:
    """Simple hash key from request fields."""
    offsets_hash = hash(tuple(req.t_offsets_s[:10])) if req.t_offsets_s else 0
    return f"{req.epoch_iso}|{len(req.t_offsets_s)}|{offsets_hash}"


# ── Request / Response models ──────────────────────────────────────────────

class SolarRequest(BaseModel):
    """Input for the solar ephemeris endpoint."""
    epoch_iso: str = Field(
        ..., description="ISO-8601 reference epoch (e.g. '2025-03-20T12:00:00Z')"
    )
    t_offsets_s: List[float] = Field(
        ..., description="Time offsets in seconds from epoch"
    )


class SolarResponse(BaseModel):
    """Solar ephemeris arrays aligned with input timestamps."""
    sun_dir_eci: List[List[float]] = Field(
        ..., description="Unit vectors [x,y,z] Earth→Sun in ECI J2000"
    )
    gmst_rad: List[float] = Field(
        ..., description="Greenwich Mean Sidereal Time in radians"
    )
    subsolar_lat_lon: List[List[float]] = Field(
        ..., description="Sub-solar point [lat, lon] in degrees"
    )


# ── Endpoint ───────────────────────────────────────────────────────────────

@router.post("/solar", response_model=SolarResponse)
async def solar_ephemeris(req: SolarRequest) -> SolarResponse:
    """Compute sun direction + GMST + sub-solar point for each timestep.

    Heavy computation runs in a thread pool to avoid blocking the event loop.
    Results are cached for repeated identical requests.
    """
    global _cache_key, _cache_val

    key = _make_cache_key(req)
    if key == _cache_key and _cache_val is not None:
        return SolarResponse(**_cache_val)

    result = await run_in_threadpool(
        compute_solar_ephemeris, req.epoch_iso, req.t_offsets_s
    )

    _cache_key = key
    _cache_val = result

    return SolarResponse(**result)


# ── Scene Timeline (heliocentric mode) ─────────────────────────────────────

_stl_cache_key: str | None = None
_stl_cache_val: dict | None = None


class SceneTimelineRequest(BaseModel):
    """Input for the heliocentric scene timeline endpoint."""
    epoch_iso: str = Field(
        ..., description="ISO-8601 reference epoch"
    )
    interval_s: float = Field(
        ..., gt=0, description="Total interval in seconds (e.g. 86400 for 1 day)"
    )
    step_s: float = Field(
        ..., gt=0, description="Step size in seconds (e.g. 3600 for 1 hour)"
    )


class SceneTimelineResponse(BaseModel):
    """Heliocentric scene timeline arrays."""
    t_offsets_s: List[float] = Field(
        ..., description="Time offsets from epoch in seconds"
    )
    earth_pos_eci_au: List[List[float]] = Field(
        ..., description="Earth heliocentric position [x,y,z] in AU (J2000 ECI)"
    )
    sun_dir_eci: List[List[float]] = Field(
        ..., description="Unit vectors [x,y,z] Earth→Sun in ECI J2000"
    )
    gmst_rad: List[float] = Field(
        ..., description="Greenwich Mean Sidereal Time in radians"
    )


@router.post("/scene-timeline", response_model=SceneTimelineResponse)
async def scene_timeline(req: SceneTimelineRequest) -> SceneTimelineResponse:
    """Compute Earth heliocentric positions + solar data for scene rendering.

    Used by the Sun-centred annual 3D mode.
    """
    global _stl_cache_key, _stl_cache_val

    key = f"{req.epoch_iso}|{req.interval_s}|{req.step_s}"
    if key == _stl_cache_key and _stl_cache_val is not None:
        return SceneTimelineResponse(**_stl_cache_val)

    result = await run_in_threadpool(
        compute_scene_timeline, req.epoch_iso, req.interval_s, req.step_s
    )

    _stl_cache_key = key
    _stl_cache_val = result

    return SceneTimelineResponse(**result)
