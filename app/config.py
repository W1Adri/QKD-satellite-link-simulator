# ---------------------------------------------------------------------------
# app/config.py
# ---------------------------------------------------------------------------
# Purpose : Centralized configuration module.  Every tuneable value (server
#           address, external API URLs, database path, log level) is loaded
#           from environment variables here with sensible defaults so that
#           the application runs out-of-the-box without a .env file but can
#           be overridden for staging / production deployments.
#
#           Call ``load_dotenv()`` is executed at import time so that a
#           ``.env`` file in the project root is picked up automatically
#           before any other module reads os.environ.
# ---------------------------------------------------------------------------
from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env file if it exists (no-op when absent)
load_dotenv()

# ── Server ───────────────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

# ── Database ─────────────────────────────────────────────────────────────
# Empty string means "use the default app/data/app.sqlite3 path".
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "")

# ── External API base URLs ───────────────────────────────────────────────
CELESTRAK_BASE_URL: str = os.getenv("CELESTRAK_BASE_URL", "https://celestrak.org")
OPEN_METEO_BASE_URL: str = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com")
# Archive API is separate from the forecast API — uses ERA5 reanalysis historical data
OPEN_METEO_ARCHIVE_URL: str = os.getenv(
    "OPEN_METEO_ARCHIVE_URL",
    "https://archive-api.open-meteo.com/v1/archive",
)

# ── Logging ───────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Request limits ────────────────────────────────────────────────────────
MAX_REQUEST_SIZE_BYTES: int = int(os.getenv("MAX_REQUEST_SIZE_BYTES", str(1 * 1024 * 1024)))  # 1 MB default
