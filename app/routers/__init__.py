# ---------------------------------------------------------------------------
# app/routers/__init__.py
# ---------------------------------------------------------------------------
# Purpose : FastAPI router sub-package.  Each module defines an APIRouter
#           that is included by the application factory in ``backend.py``.
#
# Routers:
#   pages          – HTML page serving (index, layouts, orbit3d)
#   ogs            – OGS CRUD
#   atmosphere     – atmospheric profile & weather-field endpoints
#   orbital        – orbital mechanics helpers (sun-sync, Walker, RGT)
#   users          – user accounts & chat
#   tles           – TLE constellation access
#   constellation  – constellation analysis with cosmica/SGP4
#   solver         – unified POST /api/solve endpoint
# ---------------------------------------------------------------------------
