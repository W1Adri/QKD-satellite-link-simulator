# ---------------------------------------------------------------------------
# app/logging_config.py
# ---------------------------------------------------------------------------
# Purpose : Configure structured logging for the entire application.
#
# Functions:
#   setup_logging()  - call once at app startup to configure root logger
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import logging.config
import sys

from .config import LOG_LEVEL


def setup_logging() -> None:
    """Configure root logger with structured format and level from config."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)
