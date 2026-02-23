# ---------------------------------------------------------------------------
# app/services/irradiance_svc.py
# ---------------------------------------------------------------------------
# Purpose : Service layer for solar irradiance at an OGS.  Offers two
#           strategies:
#             1. **Open-Meteo** — fetches measured / forecast irradiance
#                (GHI, DNI, DHI, diffuse, shortwave) from the Open-Meteo
#                Solar Radiation API for the station's coordinates and time.
#             2. **Analytical** — uses the clear-sky model implemented in
#                ``app.physics.irradiance`` (no external network call).
#
# Main function:
#   get_irradiance(query) → dict
#
# Exports :
#   IrradianceQuery   – frozen dataclass with lat/lon/time/method/altitude
#   IrradianceService – thin facade used by the router
# ---------------------------------------------------------------------------
from __future__ import annotations

import copy
import math
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence, Tuple

import requests

from ..physics.irradiance import compute_irradiance

logger = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────────────────────────

class IrradianceError(Exception):
    """Base exception for irradiance service errors."""


class IrradianceProviderError(IrradianceError):
    """Open-Meteo or external provider failure."""


class IrradianceParameterError(IrradianceError):
    """Invalid user parameters."""


# ── Query type ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IrradianceQuery:
    lat: float
    lon: float
    timestamp: datetime
    method: str = "analytical"      # "analytical" | "open-meteo"
    altitude_m: float = 0.0

    @property
    def date_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def hour_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:00")


# ── Open-Meteo solar radiation fetch ─────────────────────────────────────

OPEN_METEO_SOLAR_URL = "https://api.open-meteo.com/v1/forecast"

# Hourly variables to request for solar radiation
OPEN_METEO_SOLAR_VARS = (
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "terrestrial_radiation",
)


@lru_cache(maxsize=64)
def _om_solar_cached(
    lat: float, lon: float, date: str, variables: Tuple[str, ...],
) -> Dict[str, Any]:
    """Cached Open-Meteo request for solar radiation data."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date,
        "end_date": date,
        "timezone": "UTC",
        "hourly": ",".join(variables),
    }
    try:
        r = requests.get(OPEN_METEO_SOLAR_URL, params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise IrradianceProviderError(
            f"Open-Meteo solar request failed: {exc}"
        ) from exc
    data = r.json()
    if "hourly" not in data:
        raise IrradianceProviderError(
            "Open-Meteo response missing 'hourly' key"
        )
    return data


def _resolve_hour_index(hourly: Dict[str, Any], hour_key: str) -> int:
    """Find the index in the hourly time array matching the target hour."""
    tl = hourly.get("time")
    if not isinstance(tl, list):
        raise IrradianceProviderError("Missing timeline in Open-Meteo response")
    try:
        return tl.index(hour_key)
    except ValueError as exc:
        raise IrradianceProviderError(
            f"No sample for {hour_key} in Open-Meteo response"
        ) from exc


def fetch_openmeteo_irradiance(query: IrradianceQuery) -> Dict[str, Any]:
    """Fetch irradiance from Open-Meteo for a single lat/lon/time point.

    Returns a dict with GHI, DNI, DHI values (W/m²) and metadata.
    """
    raw = _om_solar_cached(
        round(query.lat, 3),
        round(query.lon, 3),
        query.date_key,
        OPEN_METEO_SOLAR_VARS,
    )
    data = copy.deepcopy(raw)
    hourly = data["hourly"]
    idx = _resolve_hour_index(hourly, query.hour_key)

    def _val(key: str) -> Optional[float]:
        arr = hourly.get(key)
        if isinstance(arr, list) and idx < len(arr):
            v = arr[idx]
            return float(v) if v is not None else None
        return None

    ghi = _val("shortwave_radiation")         # GHI (W/m²)
    dni = _val("direct_normal_irradiance")     # DNI (W/m²)
    direct_horiz = _val("direct_radiation")    # Direct horizontal (W/m²)
    dhi = _val("diffuse_radiation")            # DHI (W/m²)
    etr = _val("terrestrial_radiation")        # Extra-terrestrial radiation

    # Determine is_day: GHI > 0 or sun elevation > 0
    is_day = (ghi is not None and ghi > 0) or (direct_horiz is not None and direct_horiz > 0)

    # Compute solar elevation from GHI & DNI if possible
    solar_elevation = None
    if dni is not None and dni > 0 and ghi is not None and dhi is not None:
        # GHI = DNI * sin(elevation) + DHI
        sin_elev = (ghi - dhi) / dni if dni > 0 else 0
        sin_elev = max(-1.0, min(1.0, sin_elev))
        solar_elevation = math.degrees(math.asin(sin_elev))

    # Get all 24 hours for a daily profile
    all_ghi = hourly.get("shortwave_radiation", [])
    all_dni = hourly.get("direct_normal_irradiance", [])
    all_dhi = hourly.get("diffuse_radiation", [])
    all_times = hourly.get("time", [])

    return {
        "method": "open-meteo",
        "ghi_w_m2": round(ghi, 2) if ghi is not None else 0.0,
        "dni_w_m2": round(dni, 2) if dni is not None else 0.0,
        "dhi_w_m2": round(dhi, 2) if dhi is not None else 0.0,
        "direct_horizontal_w_m2": round(direct_horiz, 2) if direct_horiz is not None else 0.0,
        "extraterrestrial_w_m2": round(etr, 2) if etr is not None else None,
        "solar_elevation_deg": round(solar_elevation, 2) if solar_elevation is not None else None,
        "is_day": is_day,
        "source": "Open-Meteo Solar Radiation API",
        "timestamp_utc": query.hour_key,
        "daily_profile": {
            "times": all_times,
            "ghi_w_m2": [round(v, 2) if v is not None else 0.0 for v in all_ghi],
            "dni_w_m2": [round(v, 2) if v is not None else 0.0 for v in all_dni],
            "dhi_w_m2": [round(v, 2) if v is not None else 0.0 for v in all_dhi],
        },
    }


def fetch_analytical_irradiance(query: IrradianceQuery) -> Dict[str, Any]:
    """Compute irradiance analytically using the clear-sky model.

    Also produces a 24-hour daily profile (hourly samples).
    """
    result = compute_irradiance(
        query.lat, query.lon, query.timestamp, query.altitude_m

    )
    result["method"] = "analytical"
    result["source"] = "Clear-sky model (Spencer 1971 + Kasten & Young 1989)"
    result["timestamp_utc"] = query.hour_key

    # Build a 24-hour profile for the same day
    utc = (
        query.timestamp.astimezone(timezone.utc)
        if query.timestamp.tzinfo
        else query.timestamp.replace(tzinfo=timezone.utc)
    )
    base = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    times = []
    ghi_arr = []
    dni_arr = []
    dhi_arr = []
    for h in range(24):
        t = base.replace(hour=h)
        pt = compute_irradiance(query.lat, query.lon, t, query.altitude_m)
        times.append(t.strftime("%Y-%m-%dT%H:00"))
        ghi_arr.append(pt["ghi_w_m2"])
        dni_arr.append(pt["dni_w_m2"])
        dhi_arr.append(pt["dhi_w_m2"])

    result["daily_profile"] = {
        "times": times,
        "ghi_w_m2": ghi_arr,
        "dni_w_m2": dni_arr,
        "dhi_w_m2": dhi_arr,
    }

    return result


# ── Service facade ───────────────────────────────────────────────────────

def get_irradiance(query: IrradianceQuery) -> Dict[str, Any]:
    """Dispatch to the appropriate irradiance provider."""
    method = (query.method or "analytical").lower().strip()
    if method == "open-meteo":
        return fetch_openmeteo_irradiance(query)
    elif method in ("analytical", "clear-sky", "model"):
        return fetch_analytical_irradiance(query)
    else:
        raise IrradianceParameterError(
            f"Unknown irradiance method '{method}'. Use 'analytical' or 'open-meteo'."
        )


class IrradianceService:
    """Thin service facade for dependency injection from the app factory."""

    def get_irradiance(self, query: IrradianceQuery) -> Dict[str, Any]:
        return get_irradiance(query)
