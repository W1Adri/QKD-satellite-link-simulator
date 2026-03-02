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

from pathlib import Path  # Filesystem path utilities used to locate static/data files relative to this module.

from fastapi import FastAPI  # Core FastAPI application class used to create the ASGI app instance.
from fastapi.concurrency import run_in_threadpool  # Runs blocking sync work safely from async startup/request contexts.
from fastapi.staticfiles import StaticFiles  # ASGI helper to serve assets under the /static URL path.

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
        irradiance as irradiance_router,
        ogs,
        orbital,
        pages,
        solar,
        solver,
        tles as tles_router,
        users,
    )

    ogs.set_store(ogs_store)
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
    application.include_router(solar.router)
    application.include_router(irradiance_router.router)

    # Startup hook -----------------------------------------------------------
    @application.on_event("startup")
    async def _startup() -> None:
        await run_in_threadpool(database.initialise)

    return application


# ── Module-level instance for ``uvicorn app.backend:app`` ────────────────
app = create_app()
