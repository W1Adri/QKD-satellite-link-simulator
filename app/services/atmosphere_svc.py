# ---------------------------------------------------------------------------
# app/services/atmosphere_svc.py
# ---------------------------------------------------------------------------
# Purpose : Facade that builds atmospheric Cn² profiles by dispatching to the
#           appropriate provider (Hufnagel-Valley, Bufton, or Greenwood).
#
# Classes / Functions:
#   AtmosphereQuery           – frozen dataclass with query params
#   AtmosphericLayer          – single altitude layer
#   AtmosphericSummary        – integrated turbulence parameters
#   AtmosphericProfile        – full result with layers + summary
#   OpenMeteoClient           – cached REST client for Open-Meteo
#   AtmosphereService.build_profile(query) – entry point
#
# The heavy maths for each Cn² model lives in
# ``app.physics.atmosphere_models``.
# ---------------------------------------------------------------------------
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


# ── Exceptions ───────────────────────────────────────────────────────────

class AtmosphereModelError(RuntimeError):
    pass

class AtmosphereProviderError(AtmosphereModelError):
    pass

class AtmosphereModelNotFoundError(AtmosphereModelError):
    pass


# ── Query / result types ─────────────────────────────────────────────────

@dataclass(frozen=True)
class AtmosphereQuery:
    lat: float
    lon: float
    timestamp: datetime
    model: str
    ground_cn2_day: float
    ground_cn2_night: float
    wavelength_nm: float

    @property
    def is_day(self) -> bool:
        return 6 <= self.timestamp.hour < 18

    @property
    def ground_cn2(self) -> float:
        return self.ground_cn2_day if self.is_day else self.ground_cn2_night

    @property
    def hour_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:00")

    @property
    def date_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")


@dataclass
class AtmosphericLayer:
    alt_km: float
    cn2: Optional[float] = None
    wind_mps: Optional[float] = None
    temperature_k: Optional[float] = None
    humidity: Optional[float] = None


@dataclass
class AtmosphericSummary:
    r0_zenith: Optional[float] = None
    fG_zenith: Optional[float] = None
    theta0_zenith: Optional[float] = None
    wind_rms: Optional[float] = None
    loss_aod_db: Optional[float] = None
    loss_abs_db: Optional[float] = None
    coherence_time_ms: Optional[float] = None
    scintillation_index: Optional[float] = None


@dataclass
class AtmosphericProfile:
    model: str
    status: str
    timestamp: str
    summary: AtmosphericSummary
    layers: List[AtmosphericLayer]
    sources: Dict[str, Any]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "status": self.status,
            "timestamp": self.timestamp,
            "summary": _clean(asdict(self.summary)),
            "layers": [_clean(asdict(l)) for l in self.layers],
            "sources": self.sources,
            "metadata": self.metadata,
        }


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ── Open-Meteo client ────────────────────────────────────────────────────

class OpenMeteoClient:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def fetch_hourly(
        self, query: AtmosphereQuery, variables: Sequence[str],
    ) -> Dict[str, Any]:
        if not variables:
            raise AtmosphereProviderError("No variables requested")
        vt = tuple(sorted(set(variables)))
        raw = _om_cached(
            round(query.lat, 3), round(query.lon, 3), query.date_key, vt
        )
        return copy.deepcopy(raw)


@lru_cache(maxsize=128)
def _om_cached(
    lat: float, lon: float, date: str, variables: Tuple[str, ...],
) -> Dict[str, Any]:
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": date, "end_date": date,
        "timezone": "UTC", "hourly": ",".join(variables),
    }
    try:
        r = requests.get(OpenMeteoClient.BASE_URL, params=params, timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise AtmosphereProviderError(f"Open-Meteo failed: {exc}") from exc
    data = r.json()
    if "hourly" not in data:
        raise AtmosphereProviderError("Missing 'hourly' in response")
    return data


def resolve_hour_index(hourly: Dict[str, Any], hour_key: str) -> int:
    tl = hourly.get("time")
    if not isinstance(tl, list):
        raise AtmosphereProviderError("Missing timeline")
    try:
        return tl.index(hour_key)
    except ValueError as exc:
        raise AtmosphereProviderError(
            f"No sample for {hour_key}"
        ) from exc


# ── Service facade ───────────────────────────────────────────────────────

# Provider registry is populated lazily to avoid circular imports.  The
# providers themselves live in ``app.physics.atmosphere_models``.

_PROVIDERS: Optional[Dict[str, Any]] = None


def _get_providers() -> Dict[str, Any]:
    global _PROVIDERS
    if _PROVIDERS is None:
        from ..physics.atmosphere_models import PROVIDERS as P  # type: ignore
        _PROVIDERS = P
    return _PROVIDERS


def resolve_model_name(model: str) -> str:
    norm = (model or "").strip().lower()
    if not norm or norm == "auto":
        return "hufnagel-valley"
    if norm not in _get_providers():
        raise AtmosphereModelNotFoundError(f"Unknown model '{model}'")
    return norm


def build_profile(
    query: AtmosphereQuery,
    client: Optional[OpenMeteoClient] = None,
) -> Dict[str, Any]:
    name = resolve_model_name(query.model)
    fn = _get_providers()[name]
    c = client or OpenMeteoClient()
    return fn(query, c).to_dict()


class AtmosphereService:
    """Thin facade used by routers."""

    def __init__(self) -> None:
        self._client = OpenMeteoClient()

    def build_profile(self, query: AtmosphereQuery) -> Dict[str, Any]:
        return build_profile(query, self._client)
