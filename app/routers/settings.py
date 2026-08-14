# ---------------------------------------------------------------------------
# app/routers/settings.py
# ---------------------------------------------------------------------------
# Purpose : User-local runtime settings persisted to a gitignored JSON file
#           (`ion_token.json` at the project root). Holds the Cesium Ion access
#           token and the imagery mode so the frontend can read them at startup
#           and the Settings dialog can save a new token without rebuilding.
#
# Endpoints:
#   GET  /api/settings  ->  SettingsModel   (reads the file; defaults if absent)
#   POST /api/settings  ->  SettingsModel   (writes the file)
#
# NOTE: This stores a read-only-scope token in a plaintext local file. Fine for
# a single-user desktop-style app (the intended deployment); NOT suitable as a
# multi-tenant public web server. The file is gitignored so it never leaks.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["settings"])
logger = logging.getLogger(__name__)

# Project root = three levels up from app/routers/settings.py (── routers ── app ── root)
_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "ion_token.json"

_DEFAULTS = {"ionToken": "", "imageryMode": "ion"}


class SettingsModel(BaseModel):
    """User-local runtime settings (frontend imagery/Ion configuration)."""
    ionToken: str = Field("", description="Cesium Ion access token (read-only scope)")
    imageryMode: str = Field("ion", description="Imagery backend: 'ion' | 'free'")


def _read_settings() -> dict:
    """Load settings from disk, returning safe defaults on any error/absence."""
    try:
        if _SETTINGS_PATH.exists():
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            mode = str(data.get("imageryMode", "ion") or "ion")
            return {
                "ionToken": str(data.get("ionToken", "") or ""),
                "imageryMode": mode if mode in ("ion", "free") else "ion",
            }
    except Exception as exc:  # pragma: no cover - defensive I/O guard
        logger.warning("Failed reading %s: %s", _SETTINGS_PATH.name, exc)
    return dict(_DEFAULTS)


def _write_settings(settings: SettingsModel) -> dict:
    """Persist settings to the gitignored JSON file; return what was written."""
    mode = settings.imageryMode if settings.imageryMode in ("ion", "free") else "ion"
    payload = {"ionToken": settings.ionToken.strip(), "imageryMode": mode}
    _SETTINGS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


@router.get("/settings", response_model=SettingsModel)
async def get_settings() -> SettingsModel:
    """Return the persisted runtime settings (Ion token + imagery mode)."""
    return SettingsModel(**(await run_in_threadpool(_read_settings)))


@router.post("/settings", response_model=SettingsModel)
async def save_settings(req: SettingsModel) -> SettingsModel:
    """Persist the supplied settings to disk and echo the stored values back."""
    return SettingsModel(**(await run_in_threadpool(_write_settings, req)))
