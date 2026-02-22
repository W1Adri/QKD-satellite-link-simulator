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
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_PATH = STATIC_DIR / "ogs_locations.json"

# ── Service singletons ──────────────────────────────────────────────────
from .services.database import DatabaseGateway        # noqa: E402
from .services.ogs_store import OGSStore              # noqa: E402
from .services.atmosphere_svc import AtmosphereService  # noqa: E402
from .services.weather_svc import WeatherFieldService   # noqa: E402
from .services.tle_service import TleService            # noqa: E402


def create_app() -> FastAPI:
    """Application factory – constructs and returns the configured app."""

    application = FastAPI(title="QKD Europe Planner", version="0.3.0")

    # Static files -----------------------------------------------------------
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Service instances ------------------------------------------------------
    database = DatabaseGateway(BASE_DIR)
    ogs_store = OGSStore(DATA_PATH)
    atmosphere = AtmosphereService()
    weather = WeatherFieldService()
    tles = TleService()

    # Inject services into routers -------------------------------------------
    from .routers import (  # noqa: E402
        atmosphere as atmo_router,
        constellation,
        ogs,
        orbital,
        pages,
        solver,
        tles as tles_router,
        users,
    )

    ogs.set_store(ogs_store)
    users.set_database(database)
    tles_router.set_tle_service(tles)
    atmo_router.set_services(atmosphere, weather)

    # Include routers --------------------------------------------------------
    application.include_router(pages.router)
    application.include_router(ogs.router)
    application.include_router(atmo_router.router)
    application.include_router(orbital.router)
    application.include_router(users.router)
    application.include_router(tles_router.router)
    application.include_router(constellation.router)
    application.include_router(solver.router)

    # Startup hook -----------------------------------------------------------
    @application.on_event("startup")
    async def _startup() -> None:
        await run_in_threadpool(database.initialise)

    return application


# ── Module-level instance for ``uvicorn app.backend:app`` ────────────────
app = create_app()
