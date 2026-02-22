# ---------------------------------------------------------------------------
# app/routers/pages.py
# ---------------------------------------------------------------------------
# Purpose : Serve HTML pages (index, layout variants, orbit3d, favicon).
#
# Endpoints:
#   GET /                            – main SPA page
#   GET /layouts/{variant}           – dashboard / immersive variants
#   GET /static/version-{v}.html     – legacy alias
#   GET /orbit3d                     – standalone 3-D viewer
#   GET /favicon.ico                 – site icon
#   GET /health                      – liveness check
# ---------------------------------------------------------------------------
from __future__ import annotations

from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_HTML = STATIC_DIR / "index.html"
ORBIT3D_HTML = STATIC_DIR / "orbit3d.html"
FAVICON_PATH = STATIC_DIR / "favicon.ico"


def _load_variant(name: str) -> str | None:
    """Try to load a layout template from the templates/ folder."""
    path = TEMPLATES_DIR / f"{name}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if FAVICON_PATH.exists():
        return FileResponse(str(FAVICON_PATH))
    return Response(status_code=204)


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def root():
    if not INDEX_HTML.exists():
        return HTMLResponse("index.html not found", status_code=404)
    return FileResponse(str(INDEX_HTML))


@router.get("/layouts/{variant}", response_class=HTMLResponse)
async def layout_page(variant: str):
    content = _load_variant(variant.lower())
    if content is None:
        raise HTTPException(404, "Layout not available.")
    return HTMLResponse(content)


@router.get("/static/version-{variant}.html", include_in_schema=False)
async def legacy_layout(variant: str):
    content = _load_variant(variant.lower())
    if content is None:
        raise HTTPException(404, "Layout not available.")
    return HTMLResponse(content)


@router.get("/orbit3d", response_class=HTMLResponse)
async def orbit3d():
    if not ORBIT3D_HTML.exists():
        return HTMLResponse("orbit3d.html not found", 404)
    return FileResponse(str(ORBIT3D_HTML))
