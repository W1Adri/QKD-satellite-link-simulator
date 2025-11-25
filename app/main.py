"""Backward compatible shim.

This module now simply exposes the unified backend app so existing imports such as
``uvicorn app.main:app`` keep working without duplicating logic.
"""

from .backend import app  # noqa: F401

__all__ = ["app"]
from pathlib import Path

from datetime import datetime
