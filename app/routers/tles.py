# ---------------------------------------------------------------------------
# app/routers/tles.py
# ---------------------------------------------------------------------------
# Purpose : TLE (Two-Line Element) data access via CelesTrak.
#
# Endpoints:
#   GET /api/tles             – list available TLE groups
#   GET /api/tles/{group_id}  – fetch TLE data for a group
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/api", tags=["TLE"])

_tle_svc = None  # type: ignore


def set_tle_service(svc) -> None:  # noqa: ANN001
    global _tle_svc
    _tle_svc = svc


@router.get("/tles")
async def list_tle_groups() -> Dict[str, Any]:
    groups = await run_in_threadpool(_tle_svc.list_groups)
    return {"groups": groups}


@router.get("/tles/{group_id}")
async def fetch_tle_group(group_id: str):
    try:
        return await run_in_threadpool(_tle_svc.get_group, group_id)
    except Exception as exc:
        status = 404 if "not found" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
