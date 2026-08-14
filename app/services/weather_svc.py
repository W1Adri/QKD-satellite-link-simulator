# ---------------------------------------------------------------------------
# app/services/weather_svc.py
# ---------------------------------------------------------------------------
# Purpose : Build gridded weather fields by sampling Open-Meteo at multiple
#           lat/lon points for a specific variable & pressure level.
#
# Classes:
#   WeatherFieldService          – facade used by routers
#
# Functions:
#   build_weather_field(query)   – returns a grid of sampled values
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .atmosphere_svc import (
    AtmosphereProviderError,
    OpenMeteoClient,
    resolve_hour_index,
)


class WeatherFieldError(RuntimeError):
    pass

class WeatherFieldParameterError(WeatherFieldError):
    pass


@dataclass(frozen=True)
class WeatherFieldQuery:
    timestamp: datetime
    variable: str
    level_hpa: int
    samples: int


VARIABLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "wind_speed": {
        "label": "Wind speed", "units": "m/s",
        "levels": {
            200: "wind_speed_200hPa", 250: "wind_speed_250hPa",
            300: "wind_speed_300hPa", 500: "wind_speed_500hPa",
            700: "wind_speed_700hPa", 850: "wind_speed_850hPa",
        },
    },
    "temperature": {
        "label": "Temperature", "units": "degC",
        "levels": {
            200: "temperature_200hPa", 300: "temperature_300hPa",
            500: "temperature_500hPa", 700: "temperature_700hPa",
            850: "temperature_850hPa",
        },
    },
    "relative_humidity": {
        "label": "Relative humidity", "units": "%",
        "levels": {
            700: "relative_humidity_700hPa",
            850: "relative_humidity_850hPa",
            925: "relative_humidity_925hPa",
        },
    },
    "geopotential_height": {
        "label": "Geopotential height", "units": "m",
        "levels": {
            500: "geopotential_height_500hPa",
            700: "geopotential_height_700hPa",
            850: "geopotential_height_850hPa",
        },
    },
}


def _resolve_variable(variable: str, level: int) -> Dict[str, Any]:
    key = (variable or "").strip().lower()
    if key not in VARIABLE_DEFINITIONS:
        raise WeatherFieldParameterError(f"Unsupported: '{variable}'")
    d = VARIABLE_DEFINITIONS[key]
    if level not in d["levels"]:
        raise WeatherFieldParameterError(
            f"'{variable}' not at {level} hPa"
        )
    return d


def _generate_grid(hint: int):
    s = max(16, min(900, int(hint)))
    cols = max(12, round(math.sqrt(s * 2)))
    rows = max(6, math.ceil(s / cols))
    lats = [(-80.0 + 160 * i / (rows - 1)) if rows > 1 else 0 for i in range(rows)]
    lons = [(-180.0 + 360 * i / (cols - 1)) if cols > 1 else 0 for i in range(cols)]
    return rows, cols, lats, lons


def build_weather_field(
    query: WeatherFieldQuery,
    client: Optional[OpenMeteoClient] = None,
) -> Dict[str, Any]:
    """Sample a meteorological variable on a lat/lon grid."""
    defn = _resolve_variable(query.variable, query.level_hpa)
    var_key = defn["levels"][query.level_hpa]
    rows, cols, lats, lons = _generate_grid(query.samples)
    client = client or OpenMeteoClient()

    from .atmosphere_svc import AtmosphereQuery  # reuse query type

    grid_vals: List[List[Any]] = []
    lo, hi = math.inf, -math.inf
    acc, cnt = 0.0, 0

    for lat in lats:
        row: List[Any] = []
        for lon in lons:
            q = AtmosphereQuery(
                lat=lat, lon=lon, timestamp=query.timestamp,
                model="", ground_cn2_day=0, ground_cn2_night=0,
                wavelength_nm=810,
            )
            ds = client.fetch_hourly(q, (var_key,))
            hr = ds.get("hourly", {})
            idx = resolve_hour_index(hr, q.hour_key)
            series = hr.get(var_key, [])
            v = series[idx] if idx < len(series) else None
            if v is None:
                row.append(None)
                continue
            n = float(v)
            row.append(n)
            lo, hi = min(lo, n), max(hi, n)
            acc += n
            cnt += 1
        grid_vals.append(row)

    if cnt == 0 or not math.isfinite(lo):
        raise AtmosphereProviderError("No valid samples")

    return {
        "status": "ok",
        "timestamp": query.timestamp.replace(microsecond=0).isoformat() + "Z",
        "variable": {
            "key": query.variable, "label": defn["label"],
            "units": defn["units"], "pressure_hpa": query.level_hpa,
            "open_meteo_key": var_key,
        },
        "grid": {
            "rows": rows, "cols": cols,
            "latitudes": lats, "longitudes": lons,
            "values": grid_vals, "min": lo, "max": hi,
            "mean": acc / cnt, "valid_samples": cnt,
        },
        "metadata": {
            "requested_samples": query.samples,
            "actual_samples": rows * cols,
        },
    }


class WeatherFieldService:
    def __init__(self) -> None:
        self._client = OpenMeteoClient()

    def build_field(self, query: WeatherFieldQuery) -> Dict[str, Any]:
        return build_weather_field(query, self._client)
