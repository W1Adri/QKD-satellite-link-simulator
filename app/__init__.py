# ---------------------------------------------------------------------------
# app/__init__.py
# ---------------------------------------------------------------------------
# Purpose : Package root.  Re-exports the FastAPI ``app`` object and the
#           ``create_app`` factory so that ``uvicorn app:app`` works.
# ---------------------------------------------------------------------------
"""QKD Satellite Link Simulator – application package."""

from .backend import app, create_app  # noqa: F401
