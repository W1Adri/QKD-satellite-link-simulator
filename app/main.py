# ---------------------------------------------------------------------------
# app/main.py
# ---------------------------------------------------------------------------
# Purpose : Backward-compatible shim so ``uvicorn app.main:app`` keeps working.
# ---------------------------------------------------------------------------
"""Re-exports the FastAPI application from the unified backend module."""

from .backend import app  # noqa: F401

__all__ = ["app"]
