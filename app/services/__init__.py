# ---------------------------------------------------------------------------
# app/services/__init__.py
# ---------------------------------------------------------------------------
# Purpose : Expose service-layer modules that mediate between the FastAPI
#           routers and the low-level physics / persistence helpers.
#
# Modules:
#   database          – SQLite persistence (users, chats)
#   ogs_store         – JSON-file ground-station store
#   atmosphere_svc    – atmospheric profile builder facade
#   weather_svc       – gridded weather-field builder
#   tle_service       – CelesTrak TLE fetcher with cache
# ---------------------------------------------------------------------------
