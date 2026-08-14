# ---------------------------------------------------------------------------
# app/backend.py
# ---------------------------------------------------------------------------
# Purpose : FastAPI application factory.  This slim module wires together
#           routers, static-file serving, service singletons and the startup
#           hook.  All domain logic lives in app/physics/, app/services/ and
#           app/routers/.
#
# Usage:
#   uvicorn app.backend:app --reload
#   python run_app.py
# ---------------------------------------------------------------------------
from __future__ import annotations  # Postpone annotation evaluation (cleaner type hints, fewer import-order issues).

import logging
from pathlib import Path  # Filesystem path utilities used to locate static/data files relative to this module.

from fastapi import FastAPI  # Core FastAPI application class used to create the ASGI app instance.
from fastapi.concurrency import run_in_threadpool  # Runs blocking sync work safely from async startup/request contexts.
from fastapi.staticfiles import StaticFiles  # ASGI helper to serve assets under the /static URL path.
from starlette.middleware.base import BaseHTTPMiddleware  # Base class for ASGI middleware wrapping request/response cycle.
from starlette.requests import Request  # Typed request object used inside middleware dispatch.
from starlette.responses import JSONResponse  # Used to return structured JSON error responses from middleware.

from .config import DATABASE_PATH, MAX_REQUEST_SIZE_BYTES  # Override database location and request size cap via env vars.
from .logging_config import setup_logging

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_PATH = STATIC_DIR / "ogs_locations.json"

# ── Service singletons ──────────────────────────────────────────────────
from .services.database import DatabaseGateway        # noqa: E402  # DB access layer (users/chats bootstrap and queries).
from .services.ogs_store import OGSStore              # noqa: E402  # Persistence for OGS location records (JSON-backed store).
from .services.atmosphere_svc import AtmosphereService  # noqa: E402  # Computes atmosphere profiles used by link calculations.
from .services.weather_svc import WeatherFieldService   # noqa: E402  # Provides weather-field data for atmospheric modeling.
from .services.tle_service import TleService            # noqa: E402  # Manages TLE retrieval/lookup for orbit-related endpoints.


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum size: {MAX_REQUEST_SIZE_BYTES} bytes."},
            )
        return await call_next(request)


def create_app() -> FastAPI:
    """Application factory – constructs and returns the configured app."""
    setup_logging()

    application = FastAPI(title="QKD Europe Planner", version="0.3.0")
    logger.info("Application starting — QKD Europe Planner v%s", application.version)

    # Request size limit middleware -------------------------------------------
    application.add_middleware(RequestSizeLimitMiddleware)

    # Static files -----------------------------------------------------------
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Service instances ------------------------------------------------------
    database = DatabaseGateway(BASE_DIR, db_path=DATABASE_PATH)
    ogs_store = OGSStore(DATA_PATH)
    atmosphere = AtmosphereService()
    weather = WeatherFieldService()
    tles = TleService()

    # Inject services into routers -------------------------------------------
    from .routers import (  # noqa: E402
        atmosphere as atmo_router,
        constellation,
        irradiance as irradiance_router,
        ogs,
        orbital,
        pages,
        paper as paper_router,
        pcflos as pcflos_router,
        relay as relay_router,
        settings as settings_router,
        solar,
        solver,
        study as study_router,
        tles as tles_router,
        users,
    )

    ogs.set_store(ogs_store)
    solver.set_store(ogs_store)
    users.set_database(database)
    tles_router.set_tle_service(tles)
    atmo_router.set_services(atmosphere, weather)
    # Irradiance service (no external dependencies to inject)
    from .services.irradiance_svc import IrradianceService  # noqa: E402
    irradiance_router.set_service(IrradianceService())

    # Include routers --------------------------------------------------------
    application.include_router(pages.router)
    application.include_router(ogs.router)
    application.include_router(atmo_router.router)
    application.include_router(orbital.router)
    application.include_router(users.router)
    application.include_router(tles_router.router)
    application.include_router(constellation.router)
    application.include_router(solver.router)
    application.include_router(paper_router.router)
    application.include_router(solar.router)
    application.include_router(irradiance_router.router)
    application.include_router(pcflos_router.router)
    application.include_router(relay_router.router)
    application.include_router(settings_router.router)
    application.include_router(study_router.router)

    # Startup hook -----------------------------------------------------------
    @application.on_event("startup")
    async def _startup() -> None:
        await run_in_threadpool(database.initialise)

    return application


# ── Module-level instance for ``uvicorn app.backend:app`` ────────────────
app = create_app()
