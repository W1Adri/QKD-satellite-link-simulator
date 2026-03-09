# ---------------------------------------------------------------------------
# app/routers/ogs.py
# ---------------------------------------------------------------------------
# Purpose : CRUD endpoints for Optical Ground Stations (OGS).
#
# Endpoints:
#   GET    /api/ogs              – list all stations
#   POST   /api/ogs              – create / update a station
#   DELETE /api/ogs               – delete all stations
#   DELETE /api/ogs/{station_id}  – delete one station by id
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from uuid import uuid4

from ..models import OGSLocation

router = APIRouter(prefix="/api/ogs", tags=["OGS"])

# The store is injected by the application factory (see backend.py).
_store = None  # type: ignore


def set_store(store) -> None:  # noqa: ANN001
    global _store
    _store = store


@router.get("", response_model=List[OGSLocation])
async def list_ogs():
    raw = await run_in_threadpool(_store.list)
    needs_write = False
    processed: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw):
        rec = dict(item)
        if "aperture_m" not in rec or not isinstance(rec["aperture_m"], (int, float)):
            rec["aperture_m"] = 1.0
            needs_write = True
        if "altitude_m" not in rec or not isinstance(rec["altitude_m"], (int, float)):
            rec["altitude_m"] = 0.0
            needs_write = True
        if not rec.get("id"):
            rec["id"] = f"station-{uuid4().hex[:8]}-{idx}"
            needs_write = True
        processed.append(rec)
    if needs_write:
        await run_in_threadpool(_store.overwrite, processed)
    return processed


@router.post("", response_model=OGSLocation)
async def add_ogs(loc: OGSLocation):
    rec = await run_in_threadpool(_store.upsert, loc.dict())
    return OGSLocation(**rec)


@router.delete("")
async def clear_ogs():
    await run_in_threadpool(_store.delete_user_stations)
    return JSONResponse({"status": "ok", "message": "User-created stations deleted."})


@router.delete("/{station_id}")
async def delete_ogs(station_id: str):
    is_builtin = await run_in_threadpool(_store.is_builtin, station_id)
    if is_builtin:
        raise HTTPException(403, "Built-in stations cannot be deleted.")
    removed = await run_in_threadpool(_store.delete, station_id)
    if not removed:
        raise HTTPException(404, "Station not found.")
    return JSONResponse({"status": "ok", "deleted": station_id})
