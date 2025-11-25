"""Unified backend module exposing an object-oriented facade for the QKD planner.

This file consolidates the previous `database`, `atmosphere`, `meteo_field` and
`main` modules into a set of collaborating classes so the FastAPI application can
be wired together declaratively.  The functional building blocks remain the same,
but they now live in one place and are orchestrated through well defined
services.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import re
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from functools import lru_cache
from math import ceil, inf, isfinite, sqrt
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from uuid import uuid4

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Persistence layer (formerly database.py)
# ---------------------------------------------------------------------------


@dataclass
class UserRecord:
    id: int
    username: str
    created_at: str


@dataclass
class ChatRecord:
    id: int
    user_id: int
    username: str
    message: str
    created_at: str


class UserAlreadyExistsError(RuntimeError):
    """Raised when attempting to create a duplicated username."""


class DatabaseGateway:
    """Lightweight SQLite helper that exposes high level persistence methods."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent
        self.data_dir = self.base_dir / "data"
        self.db_path = self.data_dir / "app.sqlite3"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def initialise(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (DATETIME('now'))
                );

                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (DATETIME('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()
            # Remaining providers mirror the original implementation.



    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def _hash_password(self, password: str) -> str:
        digest = hashlib.sha256()
        digest.update(password.encode("utf-8"))
        return digest.hexdigest()

    def create_user(self, username: str, password: str) -> UserRecord:
        password_hash = self._hash_password(password)
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
            except sqlite3.IntegrityError as exc:
                raise UserAlreadyExistsError(username) from exc
            user_id = cursor.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return UserRecord(**dict(row))

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[UserRecord]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def verify_credentials(self, username: str, password: str) -> Optional[UserRecord]:
        password_hash = self._hash_password(password)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE username = ? AND password_hash = ?",
                (username, password_hash),
            ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def store_chat_message(self, user_id: int, message: str) -> ChatRecord:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO chats (user_id, message) VALUES (?, ?)",
                (user_id, message),
            )
            chat_id = cursor.lastrowid
            conn.commit()
            row = conn.execute(
                """
                SELECT chats.id, chats.user_id, users.username, chats.message, chats.created_at
                FROM chats
                JOIN users ON users.id = chats.user_id
                WHERE chats.id = ?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo recuperar el mensaje recién insertado")
        return ChatRecord(**dict(row))

    def list_chat_messages(self, limit: int = 50) -> List[ChatRecord]:
        limit = max(1, min(limit, 500))
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT chats.id, chats.user_id, users.username, chats.message, chats.created_at
                FROM chats
                JOIN users ON users.id = chats.user_id
                ORDER BY chats.created_at DESC, chats.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [ChatRecord(**dict(row)) for row in rows][::-1]

    def count_users(self) -> int:
        with self.connection() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(count)


# ---------------------------------------------------------------------------
# Domain services for file based storage (OGS list)
# ---------------------------------------------------------------------------


class OGSStore:
    """Manages the JSON file where ground stations are persisted."""

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        if not self.data_path.exists():
            self.data_path.write_text("[]", encoding="utf-8")

    def _read(self) -> List[Dict[str, Any]]:
        with self.data_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: List[Dict[str, Any]]) -> None:
        with self.data_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def list(self) -> List[Dict[str, Any]]:
        return self._read()

    def overwrite(self, payload: List[Dict[str, Any]]) -> None:
        self._write(payload)

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._read()
        identifier = payload.get("id") or f"station-{uuid4().hex[:8]}"
        payload = {**payload, "id": identifier}
        for idx, record in enumerate(data):
            if record.get("id") == identifier:
                data[idx] = payload
                self._write(data)
                return payload
        data.append(payload)
        self._write(data)
        return payload

    def delete_all(self) -> None:
        self._write([])

    def delete(self, station_id: str) -> bool:
        data = self._read()
        filtered = [item for item in data if item.get("id") != station_id]
        if len(filtered) == len(data):
            return False
        self._write(filtered)
        return True


# ---------------------------------------------------------------------------
# Atmospheric modelling (adapted from atmosphere.py)
# ---------------------------------------------------------------------------


class AtmosphereModelError(RuntimeError):
    pass


class AtmosphereProviderError(AtmosphereModelError):
    pass


class AtmosphereModelNotFoundError(AtmosphereModelError):
    pass


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
            "summary": _clean_dict(asdict(self.summary)),
            "layers": [_clean_dict(asdict(layer)) for layer in self.layers],
            "sources": self.sources,
            "metadata": self.metadata,
        }


class OpenMeteoClient:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def fetch_hourly(self, query: AtmosphereQuery, variables: Sequence[str]) -> Dict[str, Any]:
        if not variables:
            raise AtmosphereProviderError("No variables requested for Open-Meteo fetch")
        variable_tuple = tuple(sorted(set(variables)))
        lat_key = round(query.lat, 3)
        lon_key = round(query.lon, 3)
        raw = _fetch_open_meteo_cached(lat_key, lon_key, query.date_key, variable_tuple)
        return copy.deepcopy(raw)


@lru_cache(maxsize=128)
def _fetch_open_meteo_cached(
    lat_key: float,
    lon_key: float,
    date_key: str,
    variable_tuple: Tuple[str, ...],
) -> Dict[str, Any]:
    params = {
        "latitude": lat_key,
        "longitude": lon_key,
        "start_date": date_key,
        "end_date": date_key,
        "timezone": "UTC",
        "hourly": ",".join(variable_tuple),
    }
    try:
        response = requests.get(OpenMeteoClient.BASE_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AtmosphereProviderError(f"Open-Meteo request failed: {exc}") from exc
    data = response.json()
    if "hourly" not in data:
        raise AtmosphereProviderError("Open-Meteo response missing 'hourly' block")
    return data


def _clean_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _resolve_hour_index(hourly_block: Dict[str, Any], hour_key: str) -> int:
    timeline = hourly_block.get("time")
    if not isinstance(timeline, list):
        raise AtmosphereProviderError("Open-Meteo hourly timeline unavailable")
    try:
        return timeline.index(hour_key)
    except ValueError as exc:
        raise AtmosphereProviderError(f"No Open-Meteo sample available for {hour_key}") from exc


def _calculate_summary_from_layers(
    layers: Iterable[AtmosphericLayer],
    wavelength_nm: float,
    fallback_wind: Optional[float] = None,
    base_loss_aod: float = 0.2,
    base_loss_abs: float = 0.1,
) -> AtmosphericSummary:
    heights_m = []
    cn2_values = []
    wind_values = []
    for layer in layers:
        if layer.cn2 is None:
            continue
        heights_m.append(layer.alt_km * 1000.0)
        cn2_values.append(layer.cn2)
        wind_values.append(layer.wind_mps if layer.wind_mps is not None else fallback_wind)

    if len(cn2_values) < 2:
        return AtmosphericSummary(
            r0_zenith=0.1,
            fG_zenith=30.0,
            theta0_zenith=1.5,
            wind_rms=fallback_wind or 15.0,
            loss_aod_db=base_loss_aod,
            loss_abs_db=base_loss_abs,
        )

    heights = np.array(heights_m, dtype=float)
    cn2 = np.array(cn2_values, dtype=float)
    order = np.argsort(heights)
    heights = heights[order]
    cn2 = cn2[order]
    winds = np.array([wind_values[idx] if wind_values[idx] is not None else 0.0 for idx in order])

    k = 2.0 * math.pi / (wavelength_nm * 1e-9)
    integral_r0 = float(np.trapz(cn2, heights))
    integral_theta = float(np.trapz(cn2 * (heights ** (5.0 / 3.0)), heights))
    integral_wind = float(np.trapz(cn2 * (np.abs(winds) ** (5.0 / 3.0)), heights))

    r0_zenith = (0.423 * (k ** 2) * max(integral_r0, 1e-20)) ** (-3.0 / 5.0)
    theta0_rad = (2.91 * (k ** 2) * max(integral_theta, 1e-20)) ** (-3.0 / 5.0)
    fG_zenith = (0.102 * (k ** 2) * max(integral_wind, 1e-30)) ** (3.0 / 5.0)

    if np.count_nonzero(winds) > 0:
        wind_rms = float(np.sqrt(np.mean(winds ** 2)))
    else:
        wind_rms = fallback_wind or 15.0

    tau0 = 0.314 * r0_zenith / max(wind_rms, 1e-3)

    cn2_scale = max(integral_r0, 1e-12)
    loss_aod = base_loss_aod + min(1.8, 0.18 * (cn2_scale ** 0.3))
    loss_abs = base_loss_abs + min(1.2, 0.12 * (cn2_scale ** 0.25))

    return AtmosphericSummary(
        r0_zenith=float(r0_zenith),
        fG_zenith=float(fG_zenith),
        theta0_zenith=float(math.degrees(theta0_rad) * 3600.0),
        wind_rms=float(wind_rms),
        loss_aod_db=float(loss_aod),
        loss_abs_db=float(loss_abs),
        coherence_time_ms=float(tau0 * 1e3),
    )


def _create_layers_from_samples(
    altitudes_km: Sequence[float],
    cn2_func,
    wind_model,
    temperature_profile=None,
    humidity_profile=None,
) -> List[AtmosphericLayer]:
    layers: List[AtmosphericLayer] = []
    for alt_km in altitudes_km:
        temperature = temperature_profile(alt_km) if temperature_profile else None
        humidity = humidity_profile(alt_km) if humidity_profile else None
        layers.append(
            AtmosphericLayer(
                alt_km=alt_km,
                cn2=float(cn2_func(alt_km * 1000.0)),
                wind_mps=float(wind_model(alt_km)),
                temperature_k=temperature,
                humidity=humidity,
            )
        )
    return layers


def _hv57_provider(query: AtmosphereQuery, client: OpenMeteoClient) -> AtmosphericProfile:
    variables = ["wind_u_component_300hPa", "wind_v_component_300hPa"]
    dataset = client.fetch_hourly(query, variables)
    hourly = dataset["hourly"]
    idx = _resolve_hour_index(hourly, query.hour_key)

    wind_u = hourly.get("wind_u_component_300hPa", [None])[idx]
    wind_v = hourly.get("wind_v_component_300hPa", [None])[idx]
    if wind_u is None or wind_v is None:
        raise AtmosphereProviderError("Missing 300 hPa wind components for Hufnagel-Valley model")

    W = float(math.sqrt(wind_u ** 2 + wind_v ** 2))
    W = max(W, 5.0)
    A = max(query.ground_cn2, 1e-17)

    def cn2_hv(h_metres: float) -> float:
        term1 = 0.00594 * ((W / 27.0) ** 2) * (h_metres * 1e-5) ** 10 * math.exp(-h_metres / 1000.0)
        term2 = 2.7e-16 * math.exp(-h_metres / 1500.0)
        term3 = A * math.exp(-h_metres / 100.0)
        return term1 + term2 + term3

    def wind_profile(alt_km: float) -> float:
        return float(max(0.0, W * (1.0 - math.exp(-alt_km / 5.0)) + 3.0))

    altitudes = (0.0, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0)
    layers = _create_layers_from_samples(altitudes, cn2_hv, wind_profile)
    summary = _calculate_summary_from_layers(layers, query.wavelength_nm, fallback_wind=W)

    return AtmosphericProfile(
        model="hufnagel-valley",
        status="ok",
        timestamp=query.timestamp.replace(microsecond=0).isoformat() + "Z",
        summary=summary,
        layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": variables},
        metadata={
            "daytime": query.is_day,
            "wavelength_nm": query.wavelength_nm,
            "ground_cn2": query.ground_cn2,
            "wind_speed_300hPa": W,
        },
    )


# Remaining providers mirror the original implementation.


def _bufton_provider(query: AtmosphereQuery, client: OpenMeteoClient) -> AtmosphericProfile:
    variables = [
        "wind_u_component_300hPa",
        "wind_v_component_300hPa",
        "wind_u_component_500hPa",
        "wind_v_component_500hPa",
        "wind_u_component_850hPa",
        "wind_v_component_850hPa",
        "temperature_850hPa",
    ]
    dataset = client.fetch_hourly(query, variables)
    hourly = dataset["hourly"]
    idx = _resolve_hour_index(hourly, query.hour_key)

    def _wind_speed(key: str) -> float:
        u = hourly.get(f"wind_u_component_{key}", [None])[idx]
        v = hourly.get(f"wind_v_component_{key}", [None])[idx]
        if u is None or v is None:
            raise AtmosphereProviderError(f"Missing wind component for {key}")
        return float(math.sqrt(u ** 2 + v ** 2))

    wind_300 = _wind_speed("300hPa")
    wind_500 = _wind_speed("500hPa")
    wind_850 = _wind_speed("850hPa")

    temp_850 = hourly.get("temperature_850hPa", [None])[idx]
    lapse_correction = 0.8 if temp_850 is None else max(0.5, min(1.5, (temp_850 + 273.15) / 290.0))

    A = max(query.ground_cn2, 1e-17)
    shear_factor = max(0.5, min(2.5, abs(wind_500 - wind_850) / 10.0))

    def cn2_bufton(h_metres: float) -> float:
        h_km = h_metres / 1000.0
        if h_km < 0.5:
            return A * math.exp(-h_metres / 60.0)
        if h_km < 1.5:
            return 0.3 * A * math.exp(-h_metres / 120.0) * shear_factor
        if h_km < 5.0:
            return 0.08 * A * math.exp(-h_metres / 600.0) * lapse_correction
        return 0.02 * A * math.exp(-(h_metres - 5000.0) / 1500.0)

    def wind_profile(alt_km: float) -> float:
        if alt_km < 0.5:
            return float(max(2.0, wind_850 * 0.6))
        if alt_km < 1.5:
            return float((wind_850 + wind_500) / 2.0)
        if alt_km < 6.0:
            return float(wind_500)
        return float(wind_300)

    def temperature_profile(alt_km: float) -> Optional[float]:
        if temp_850 is None:
            return None
        lapse_rate = -6.5
        delta = alt_km - 1.5
        return float((temp_850 + 273.15) + lapse_rate * delta)

    altitudes = (0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0)
    layers = _create_layers_from_samples(altitudes, cn2_bufton, wind_profile, temperature_profile)
    summary = _calculate_summary_from_layers(
        layers,
        query.wavelength_nm,
        fallback_wind=float(np.sqrt((wind_300 ** 2 + wind_500 ** 2 + wind_850 ** 2) / 3.0)),
        base_loss_aod=0.25,
        base_loss_abs=0.12,
    )
    summary.scintillation_index = float(min(1.5, 0.3 + shear_factor * 0.2))

    return AtmosphericProfile(
        model="bufton",
        status="ok",
        timestamp=query.timestamp.replace(microsecond=0).isoformat() + "Z",
        summary=summary,
        layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": variables},
        metadata={
            "daytime": query.is_day,
            "wavelength_nm": query.wavelength_nm,
            "ground_cn2": query.ground_cn2,
            "wind_speed_300hPa": wind_300,
            "wind_speed_500hPa": wind_500,
            "wind_speed_850hPa": wind_850,
        },
    )


def _greenwood_provider(query: AtmosphereQuery, client: OpenMeteoClient) -> AtmosphericProfile:
    variables = [
        "wind_u_component_300hPa",
        "wind_v_component_300hPa",
        "wind_u_component_500hPa",
        "wind_v_component_500hPa",
        "wind_u_component_700hPa",
        "wind_v_component_700hPa",
    ]
    dataset = client.fetch_hourly(query, variables)
    hourly = dataset["hourly"]
    idx = _resolve_hour_index(hourly, query.hour_key)

    def _wind_speed(key: str) -> float:
        u = hourly.get(f"wind_u_component_{key}", [None])[idx]
        v = hourly.get(f"wind_v_component_{key}", [None])[idx]
        if u is None or v is None:
            raise AtmosphereProviderError(f"Missing wind component for {key}")
        return float(math.sqrt(u ** 2 + v ** 2))

    wind_300 = _wind_speed("300hPa")
    wind_500 = _wind_speed("500hPa")
    wind_700 = _wind_speed("700hPa")

    A = max(query.ground_cn2, 1e-17)

    def cn2_greenwood(h_metres: float) -> float:
        h_km = h_metres / 1000.0
        if h_km < 0.5:
            return A * math.exp(-h_metres / 50.0)
        if h_km < 2.0:
            return 0.2 * A * math.exp(-h_metres / 200.0)
        if h_km < 8.0:
            return 0.05 * A * math.exp(-h_metres / 900.0)
        return 0.02 * A * math.exp(-(h_metres - 8000.0) / 1500.0)

    def wind_profile(alt_km: float) -> float:
        if alt_km < 1.5:
            return float((wind_700 + wind_500) / 2.0)
        if alt_km < 5.0:
            return float((wind_500 + wind_300) / 2.0)
        return float(wind_300)

    altitudes = (0.0, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0)
    layers = _create_layers_from_samples(altitudes, cn2_greenwood, wind_profile)
    summary = _calculate_summary_from_layers(
        layers,
        query.wavelength_nm,
        fallback_wind=float((wind_300 + wind_500 + wind_700) / 3.0),
        base_loss_aod=0.22,
        base_loss_abs=0.11,
    )

    return AtmosphericProfile(
        model="greenwood",
        status="ok",
        timestamp=query.timestamp.replace(microsecond=0).isoformat() + "Z",
        summary=summary,
        layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": variables},
        metadata={
            "daytime": query.is_day,
            "wavelength_nm": query.wavelength_nm,
            "ground_cn2": query.ground_cn2,
            "wind_speed_300hPa": wind_300,
            "wind_speed_500hPa": wind_500,
            "wind_speed_700hPa": wind_700,
        },
    )


PROVIDERS = {
    "hufnagel-valley": _hv57_provider,
    "hv57": _hv57_provider,
    "bufton": _bufton_provider,
    "greenwood": _greenwood_provider,
}


def resolve_model_name(model: str) -> str:
    normalized = (model or "").strip().lower()
    if not normalized or normalized == "auto":
        return "hufnagel-valley"
    if normalized not in PROVIDERS:
        raise AtmosphereModelNotFoundError(f"Atmospheric model '{model}' is not available")
    return normalized


def build_profile(query: AtmosphereQuery, client: Optional[OpenMeteoClient] = None) -> Dict[str, Any]:
    provider_name = resolve_model_name(query.model)
    provider = PROVIDERS[provider_name]
    client = client or OpenMeteoClient()
    profile = provider(query, client)
    return profile.to_dict()


class AtmosphereService:
    """Facade around the atmospheric model helpers."""

    def __init__(self) -> None:
        self._client = OpenMeteoClient()

    def build_profile(self, query: AtmosphereQuery) -> Dict[str, Any]:
        return build_profile(query, self._client)


# ---------------------------------------------------------------------------
# Weather field sampling (adapted from meteo_field.py)
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class _HourlyPointQuery:
    lat: float
    lon: float
    timestamp: datetime

    @property
    def date_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def hour_key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:00")


VARIABLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "wind_speed": {
        "label": "Wind speed",
        "units": "m/s",
        "levels": {
            200: "wind_speed_200hPa",
            250: "wind_speed_250hPa",
            300: "wind_speed_300hPa",
            500: "wind_speed_500hPa",
            700: "wind_speed_700hPa",
            850: "wind_speed_850hPa",
        },
    },
    "temperature": {
        "label": "Temperature",
        "units": "degC",
        "levels": {
            200: "temperature_200hPa",
            300: "temperature_300hPa",
            500: "temperature_500hPa",
            700: "temperature_700hPa",
            850: "temperature_850hPa",
        },
    },
    "relative_humidity": {
        "label": "Relative humidity",
        "units": "%",
        "levels": {
            700: "relative_humidity_700hPa",
            850: "relative_humidity_850hPa",
            925: "relative_humidity_925hPa",
        },
    },
    "geopotential_height": {
        "label": "Geopotential height",
        "units": "m",
        "levels": {
            500: "geopotential_height_500hPa",
            700: "geopotential_height_700hPa",
            850: "geopotential_height_850hPa",
        },
    },
}


def _resolve_variable(variable: str, level_hpa: int) -> Dict[str, Any]:
    key = (variable or "").strip().lower()
    if key not in VARIABLE_DEFINITIONS:
        raise WeatherFieldParameterError(f"Unsupported variable '{variable}'")
    definition = VARIABLE_DEFINITIONS[key]
    if level_hpa not in definition["levels"]:
        raise WeatherFieldParameterError(
            f"Variable '{variable}' is not available at {level_hpa} hPa",
        )
    return definition


@dataclass
class _GridDefinition:
    rows: int
    cols: int
    latitudes: List[float]
    longitudes: List[float]


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


def _generate_grid(sample_hint: int) -> _GridDefinition:
    clamped_samples = max(16, min(900, int(sample_hint)))
    cols = max(12, int(round(sqrt(clamped_samples * 2))))
    rows = max(6, int(ceil(clamped_samples / cols)))

    latitudes = [
        _lerp(-80.0, 80.0, idx / (rows - 1)) if rows > 1 else 0.0
        for idx in range(rows)
    ]
    longitudes = [
        _lerp(-180.0, 180.0, idx / (cols - 1)) if cols > 1 else 0.0
        for idx in range(cols)
    ]

    return _GridDefinition(rows=rows, cols=cols, latitudes=latitudes, longitudes=longitudes)


def _resolve_hour_index(hourly_block: Dict[str, Any], hour_key: str) -> int:
    timeline = hourly_block.get("time")
    if not isinstance(timeline, list):
        raise AtmosphereProviderError("Open-Meteo hourly timeline unavailable")
    try:
        return timeline.index(hour_key)
    except ValueError as exc:
        raise AtmosphereProviderError(f"No Open-Meteo sample available for {hour_key}") from exc


def build_weather_field(query: WeatherFieldQuery, client: Optional[OpenMeteoClient] = None) -> Dict[str, Any]:
    definition = _resolve_variable(query.variable, query.level_hpa)
    variable_key = definition["levels"][query.level_hpa]
    grid = _generate_grid(query.samples)

    client = client or OpenMeteoClient()
    rows: List[List[Any]] = []
    current_min = inf
    current_max = -inf
    accumulator = 0.0
    valid_count = 0

    for lat in grid.latitudes:
        row_values: List[Any] = []
        for lon in grid.longitudes:
            point_query = _HourlyPointQuery(lat=lat, lon=lon, timestamp=query.timestamp)
            dataset = client.fetch_hourly(point_query, (variable_key,))
            hourly = dataset.get("hourly", {})
            idx = _resolve_hour_index(hourly, point_query.hour_key)
            series: Sequence[Any] = hourly.get(variable_key, [])
            value = None
            if idx < len(series):
                value = series[idx]
            if value is None:
                row_values.append(None)
                continue
            numeric = float(value)
            row_values.append(numeric)
            if numeric < current_min:
                current_min = numeric
            if numeric > current_max:
                current_max = numeric
            accumulator += numeric
            valid_count += 1
        rows.append(row_values)

    if valid_count == 0 or not isfinite(current_min) or not isfinite(current_max):
        raise AtmosphereProviderError("No valid samples returned by Open-Meteo")

    mean_value = accumulator / valid_count if valid_count else None

    return {
        "status": "ok",
        "timestamp": query.timestamp.replace(microsecond=0).isoformat() + "Z",
        "variable": {
            "key": query.variable,
            "label": definition["label"],
            "units": definition["units"],
            "pressure_hpa": query.level_hpa,
            "open_meteo_key": variable_key,
        },
        "grid": {
            "rows": grid.rows,
            "cols": grid.cols,
            "latitudes": grid.latitudes,
            "longitudes": grid.longitudes,
            "values": rows,
            "min": current_min,
            "max": current_max,
            "mean": mean_value,
            "valid_samples": valid_count,
        },
        "metadata": {
            "requested_samples": query.samples,
            "actual_samples": grid.rows * grid.cols,
        },
    }


class WeatherFieldService:
    def __init__(self) -> None:
        self._client = OpenMeteoClient()

    def build_field(self, query: WeatherFieldQuery) -> Dict[str, Any]:
        return build_weather_field(query, self._client)


@dataclass
class TleCacheEntry:
    expires_at: datetime
    payload: Dict[str, Any]


class TleServiceError(RuntimeError):
    """Base class for TLE retrieval errors."""


class TleGroupNotFoundError(TleServiceError):
    """Raised when requesting an unknown constellation group."""


class TleProviderError(TleServiceError):
    """Raised when the upstream provider returns an unexpected response."""


class TleService:
    """Fetches and caches TLE datasets from public providers."""

    CELESTRAK_ENDPOINT = "https://celestrak.org/NORAD/elements/gp.php"
    GROUP_ALIAS = {
        "starlink": "starlink",
        "oneweb": "oneweb",
        "gps": "gps-ops",
        "galileo": "galileo",
        "glonass": "glonass",
    }

    def __init__(self, cache_ttl: timedelta = timedelta(minutes=30)) -> None:
        self._cache: Dict[str, TleCacheEntry] = {}
        self._cache_ttl = cache_ttl

    def list_groups(self) -> List[str]:
        return list(self.GROUP_ALIAS.keys())

    def get_group(self, group_id: str) -> Dict[str, Any]:
        normalized = (group_id or "").strip().lower()
        if normalized not in self.GROUP_ALIAS:
            raise TleGroupNotFoundError(f"Constelación desconocida: {group_id}")

        cached = self._cache.get(normalized)
        now = datetime.utcnow()
        if cached and cached.expires_at > now:
            return copy.deepcopy(cached.payload)

        payload = self._download_group(normalized)
        expires_at = now + self._cache_ttl
        payload["fetched_at"] = now.isoformat(timespec="seconds") + "Z"
        payload["expires_at"] = expires_at.isoformat(timespec="seconds") + "Z"
        payload["ttl_seconds"] = int(self._cache_ttl.total_seconds())

        self._cache[normalized] = TleCacheEntry(expires_at=expires_at, payload=copy.deepcopy(payload))
        return payload

    def _download_group(self, normalized_group: str) -> Dict[str, Any]:
        alias = self.GROUP_ALIAS[normalized_group]
        try:
            response = requests.get(
                self.CELESTRAK_ENDPOINT,
                params={"GROUP": alias, "FORMAT": "TLE"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise TleProviderError(f"Error de conexión al proveedor TLE: {exc}") from exc

        if response.status_code != 200:
            raise TleProviderError(
                f"Proveedor TLE devolvió estado {response.status_code} para '{alias}'."
            )

        entries = self._parse_tle_response(response.text)
        if not entries:
            raise TleProviderError(f"Proveedor TLE no devolvió datos para '{alias}'.")

        return {
            "group": normalized_group,
            "alias": alias,
            "count": len(entries),
            "tles": entries,
            "source": "celestrak",
        }

    @staticmethod
    def _parse_tle_response(payload: str) -> List[Dict[str, Any]]:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]
        entries: List[Dict[str, Any]] = []
        for idx in range(0, len(lines) - 2, 3):
            name, line1, line2 = lines[idx : idx + 3]
            if not (line1.startswith("1 ") and line2.startswith("2 ")):
                continue
            norad_id = None
            tokens = line1.split()
            if len(tokens) >= 2:
                match = re.match(r"^(\d+)", tokens[1])
                if match:
                    norad_id = match.group(1)
            entries.append({"name": name, "line1": line1, "line2": line2, "norad_id": norad_id})
        return entries


# ---------------------------------------------------------------------------
# API schema models
# ---------------------------------------------------------------------------


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ORBIT3D_HTML = STATIC_DIR / "orbit3d.html"
DATA_PATH = STATIC_DIR / "ogs_locations.json"
FAVICON_PATH = STATIC_DIR / "favicon.ico"


class OGSLocation(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1)
    lat: float
    lon: float
    aperture_m: float = Field(default=1.0, ge=0.1, le=15.0)
    notes: Optional[str] = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=4, max_length=128)


class UserRead(BaseModel):
    id: int
    username: str
    created_at: str


class AuthResponse(UserRead):
    message: str


class ChatCreate(BaseModel):
    user_id: int
    message: str = Field(min_length=1, max_length=2000)


class ChatRead(BaseModel):
    id: int
    user_id: int
    username: str
    message: str
    created_at: str


class UserCount(BaseModel):
    count: int


class AtmosRequest(BaseModel):
    lat: float
    lon: float
    time: str
    ground_cn2_day: float
    ground_cn2_night: float
    model: str = Field(default="hufnagel-valley")
    wavelength_nm: Optional[float] = Field(default=810.0, ge=400.0, le=2000.0)


class WeatherFieldRequest(BaseModel):
    time: str
    variable: str = Field(default="wind_speed")
    level_hpa: int = Field(default=200, ge=50, le=1000)
    samples: int = Field(default=120, ge=16, le=900)


def is_in_europe_bbox(lat: float, lon: float) -> bool:
    return (25.0 <= lat <= 72.0) and (-31.0 <= lon <= 45.0)


def _normalize_username(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Nombre de usuario inválido")
    return value.strip().lower()


VARIANT_PAGES: Dict[str, str] = {
        "dashboard": dedent(
                """\
                <!DOCTYPE html>
                <html lang="es">
                <head>
                    <meta charset="utf-8" />
                    <meta name="viewport" content="width=device-width, initial-scale=1" />
                    <title>QKD Orbit Designer · Versión Panel</title>
                    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
                    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
                    <link rel="stylesheet" href="/static/styles/app.css" />
                    <script type="importmap">
                        {
                            "imports": {
                                "three": "https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.module.js",
                                "three/examples/": "https://cdn.jsdelivr.net/npm/three@0.160.1/examples/jsm/"
                            }
                        }
                    </script>
                </head>
                <body data-variant="dashboard">
                    <div class="app-shell">
                        <header class="app-header">
                            <div class="brand">
                                <h1>QKD Orbit Designer</h1>
                                <p class="subtitle">Versión panel · Layout analítico</p>
                            </div>
                            <nav class="variant-picker" aria-label="Cambiar de versión">
                                <a href="/">Compacta</a>
                                <a href="/layouts/dashboard" class="is-active">Panel</a>
                                <a href="/layouts/immersive">Inmersiva</a>
                            </nav>
                            <div class="header-actions">
                                <button id="btnTogglePanels" class="ghost" type="button">Ocultar paneles</button>
                                <button id="btnTheme" class="ghost" type="button" aria-pressed="false">Modo oscuro</button>
                            </div>
                        </header>

                        <main class="workspace">
                            <section class="visual-area">
                                <div class="view-grid" data-view-container>
                                    <div id="threeContainer" class="view-pane view-3d" aria-label="Globo 3D"></div>
                                    <div id="mapContainer" class="view-pane view-2d" aria-label="Mapa 2D"></div>
                                    <div class="chart-stack">
                                        <div class="chart-card">
                                            <header>
                                                <h3>Pérdidas geométricas</h3>
                                                <span id="lossSummary">--</span>
                                            </header>
                                            <div id="chartLoss"></div>
                                        </div>
                                        <div class="chart-card">
                                            <header>
                                                <h3>Elevación</h3>
                                                <span id="elevationSummary">--</span>
                                            </header>
                                            <div id="chartElevation"></div>
                                        </div>
                                        <div class="chart-card">
                                            <header>
                                                <h3>Distancia</h3>
                                                <span id="distanceSummary">--</span>
                                            </header>
                                            <div id="chartDistance"></div>
                                        </div>
                                    </div>
                                </div>
                                <div class="timeline">
                                    <div class="timeline-header">
                                        <div class="timeline-actions">
                                            <button id="btnPlay" type="button">▶</button>
                                            <button id="btnPause" type="button">⏸</button>
                                            <button id="btnStepBack" type="button">⏪</button>
                                            <button id="btnStepForward" type="button">⏩</button>
                                            <button id="btnResetTime" type="button">↺</button>
                                        </div>
                                        <div class="timeline-meta">
                                            <label for="timeWarp">Velocidad</label>
                                            <select id="timeWarp">
                                                <option value="1">x1</option>
                                                <option value="10">x10</option>
                                                <option value="60" selected>x60</option>
                                                <option value="300">x300</option>
                                                <option value="900">x900</option>
                                            </select>
                                            <span class="time-readout">t=<span id="timeLabel">0 s</span></span>
                                        </div>
                                    </div>
                                    <input id="timeSlider" type="range" min="0" max="1" step="1" value="0" />
                                </div>
                            </section>

                            <aside class="control-panel drawer" data-panel="primary" data-collapsed="false">
                                <div class="drawer-body" id="dashboard-drawer">
                                    <nav class="drawer-menu" aria-label="Paneles de control">
                                        <button type="button" class="drawer-menu-item is-active" data-section-target="orbit">Órbita</button>
                                        <button type="button" class="drawer-menu-item" data-section-target="optics">Enlace óptico</button>
                                        <button type="button" class="drawer-menu-item" data-section-target="stations">Estaciones</button>
                                    </nav>
                                    <div class="drawer-content">
                                        <section class="panel-group" data-section="orbit">
                                            <header>
                                                <h2>Orbit</h2>
                                            </header>
                                            <div class="field">
                                                <label for="satelliteName">Nombre</label>
                                                <input id="satelliteName" type="text" value="Sat-QKD" />
                                            </div>
                                            <div class="field">
                                                <label for="epochInput">Época</label>
                                                <input id="epochInput" type="datetime-local" />
                                            </div>
                                            <div class="field-columns">
                                                <label class="field">a (km)<input id="semiMajor" type="number" min="6600" max="9000" value="6771" /></label>
                                                <label class="field">e<input id="eccentricity" type="number" min="0" max="0.2" step="0.001" value="0.001" /></label>
                                                <label class="field">i (°)<input id="inclination" type="number" min="0" max="180" step="0.1" value="53" /></label>
                                                <label class="field">Ω (°)<input id="raan" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                                <label class="field">ω (°)<input id="argPerigee" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                                <label class="field">M₀ (°)<input id="meanAnomaly" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                            </div>
                                            <div class="field-columns">
                                                <label class="checkbox">
                                                    <input id="j2Toggle" type="checkbox" checked />
                                                    J2
                                                </label>
                                                <label class="checkbox">
                                                    <input id="resonanceToggle" type="checkbox" />
                                                    Resonance
                                                </label>
                                            </div>
                                            <div class="field-columns resonance" data-hidden>
                                                <label class="field">Orbits (k)<input id="resonanceOrbits" type="range" min="1" max="30" value="1" /><span id="resonanceOrbitsVal">1</span></label>
                                                <label class="field">Rotations (j)<input id="resonanceRotations" type="range" min="1" max="30" value="1" /><span id="resonanceRotationsVal">1</span></label>
                                            </div>
                                        </section>
                                        <section class="panel-group" data-section="optics" hidden>
                                            <header>
                                                <h2>Optics</h2>
                                            </header>
                                            <div class="field-columns">
                                                <label class="field">Apertura satélite (m)<input id="satAperture" type="number" min="0.1" max="3" step="0.05" value="0.6" /></label>
                                                <label class="field">Apertura estación (m)<input id="groundAperture" type="number" min="0.1" max="5" step="0.05" value="1.0" /></label>
                                                <label class="field">λ (nm)<input id="wavelength" type="number" min="600" max="1700" step="1" value="810" /></label>
                                                <label class="field">Muestras/órbita<input id="samplesPerOrbit" type="number" min="60" max="720" step="10" value="180" /></label>
                                            </div>
                                        </section>
                                        <section class="panel-group" data-section="stations" hidden>
                                            <header>
                                                <h2>Stations</h2>
                                            </header>
                                            <div class="field">
                                                <label for="stationSelect">Estación activa</label>
                                                <select id="stationSelect"></select>
                                            </div>
                                            <div class="button-row">
                                                <button id="btnAddStation" type="button">Nueva estación</button>
                                                <button id="btnFocusStation" type="button">Enfocar</button>
                                            </div>
                                            <dl class="metrics" id="stationMetrics">
                                                <div><dt>Distancia</dt><dd id="distanceMetric">--</dd></div>
                                                <div><dt>Elevación</dt><dd id="elevationMetric">--</dd></div>
                                                <div><dt>Zenit</dt><dd id="zenithMetric">--</dd></div>
                                                <div><dt>Pérdida geométrica</dt><dd id="lossMetric">--</dd></div>
                                                <div><dt>Doppler</dt><dd id="dopplerMetric">--</dd></div>
                                            </dl>
                                        </section>
                                        <section class="panel-group" data-section="constellations" hidden>
                                            <header>
                                                <h2>Constellations</h2>
                                            </header>
                                            <div class="field-columns">
                                                <label class="field">T (satélites)<input id="walkerT" type="number" min="1" max="2000" value="24" /></label>
                                                <label class="field">P (planos)<input id="walkerP" type="number" min="1" max="200" value="6" /></label>
                                                <label class="field">F (fase)<input id="walkerF" type="number" min="0" max="P-1" value="1" /></label>
                                            </div>
                                            <div class="button-row">
                                                <button id="btnPlotConstellation" type="button">Trazar constelación</button>
                                                <button id="btnClearConstellation" type="button">Limpiar constelación</button>
                                            </div>
                                            <div id="constellationControls" class="constellation-controls">
                                                <div id="constellationList"></div>
                                                <div id="constellationStatus" class="hint"></div>
                                            </div>
                                        </section>
                                    </div>
                                </div>
                                <button class="drawer-handle" type="button" data-target="primary" aria-controls="dashboard-drawer" aria-expanded="true">
                                    <span class="icon" aria-hidden="true">◀</span>
                                    <span class="label">Panel</span>
                                </button>
                            </aside>
                        </main>
                    </div>

                    <dialog id="stationDialog">
                        <form method="dialog" class="dialog-content">
                            <h2>Nueva estación</h2>
                            <label>Nombre<input id="stationName" required /></label>
                            <label>Latitud (°)<input id="stationLat" type="number" min="-90" max="90" step="0.0001" required /></label>
                            <label>Longitud (°)<input id="stationLon" type="number" min="-180" max="180" step="0.0001" required /></label>
                            <label>Apertura (m)<input id="stationAperture" type="number" min="0.1" max="8" step="0.1" value="1.0" required /></label>
                            <menu>
                                <button value="cancel">Cancelar</button>
                                <button id="stationSave" value="default">Guardar</button>
                            </menu>
                        </form>
                    </dialog>

                    <template id="stationOptionTemplate">
                        <option></option>
                    </template>

                    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
                    <script type="module" src="/static/app.js"></script>
                </body>
                </html>
                """
        ),
        "immersive": dedent(
                """\
                <!DOCTYPE html>
                <html lang="es">
                <head>
                    <meta charset="utf-8" />
                    <meta name="viewport" content="width=device-width, initial-scale=1" />
                    <title>QKD Orbit Designer · Versión Inmersiva</title>
                    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
                    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
                    <link rel="stylesheet" href="/static/styles/app.css" />
                    <script type="importmap">
                        {
                            "imports": {
                                "three": "https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.module.js",
                                "three/examples/": "https://cdn.jsdelivr.net/npm/three@0.160.1/examples/jsm/"
                            }
                        }
                    </script>
                </head>
                <body data-variant="immersive">
                    <div class="app-shell">
                        <header class="app-header">
                            <div class="brand">
                                <h1>QKD Orbit Designer</h1>
                                <p class="subtitle">Versión inmersiva · Control flotante</p>
                            </div>
                            <nav class="variant-picker" aria-label="Cambiar de versión">
                                <a href="/">Compacta</a>
                                <a href="/layouts/dashboard">Panel</a>
                                <a href="/layouts/immersive" class="is-active">Inmersiva</a>
                            </nav>
                            <div class="header-actions">
                                <button id="btnTheme" class="ghost" type="button" aria-pressed="false">Modo oscuro</button>
                            </div>
                        </header>

                        <main class="workspace">
                            <div class="immersive-stage">
                                <div id="threeContainer" class="immersive-3d" aria-label="Globo 3D"></div>
                                <div id="mapContainer" class="immersive-map" aria-label="Mapa 2D"></div>
                                <div class="immersive-overlay">
                                    <section class="floating-card" id="cardOrbit">
                                        <header>
                                            <h2>Orbit</h2>
                                            <button class="ghost" data-collapse="cardOrbit">−</button>
                                        </header>
                                        <div class="card-body">
                                            <label>Nombre<input id="satelliteName" type="text" value="Sat-QKD" /></label>
                                            <label>Época<input id="epochInput" type="datetime-local" /></label>
                                            <label>a (km)<input id="semiMajor" type="number" min="6600" max="9000" value="6771" /></label>
                                            <label>e<input id="eccentricity" type="number" min="0" max="0.2" step="0.001" value="0.001" /></label>
                                            <label>i (°)<input id="inclination" type="number" min="0" max="180" step="0.1" value="53" /></label>
                                            <label>Ω (°)<input id="raan" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                            <label>ω (°)<input id="argPerigee" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                            <label>M₀ (°)<input id="meanAnomaly" type="number" min="0" max="360" step="0.1" value="0" /></label>
                                            <label class="checkbox">
                                                <input id="j2Toggle" type="checkbox" checked />
                                                J2
                                            </label>
                                            <label class="checkbox">
                                                <input id="resonanceToggle" type="checkbox" />
                                                Resonance
                                            </label>
                                            <div class="dual" data-hidden>
                                                <label>Orbits (k)<input id="resonanceOrbits" type="range" min="1" max="30" value="1" /><span id="resonanceOrbitsVal">1</span></label>
                                                <label>Rotations (j)<input id="resonanceRotations" type="range" min="1" max="30" value="1" /><span id="resonanceRotationsVal">1</span></label>
                                            </div>
                                        </div>
                                    </section>

                                    <section class="floating-card" id="cardLink">
                                        <header>
                                            <h2>Optics</h2>
                                            <button class="ghost" data-collapse="cardLink">−</button>
                                        </header>
                                        <div class="card-body">
                                            <label>Apertura satélite (m)<input id="satAperture" type="number" min="0.1" max="3" step="0.05" value="0.6" /></label>
                                            <label>Apertura estación (m)<input id="groundAperture" type="number" min="0.1" max="5" step="0.05" value="1.0" /></label>
                                            <label>λ (nm)<input id="wavelength" type="number" min="600" max="1700" step="1" value="810" /></label>
                                            <label>Muestras/órbita<input id="samplesPerOrbit" type="number" min="60" max="720" step="10" value="180" /></label>
                                            <label class="range">Tiempo<input id="timeSlider" type="range" min="0" max="1" step="1" value="0" /></label>
                                            <div class="timeline-buttons">
                                                <button id="btnPlay" type="button">▶</button>
                                                <button id="btnPause" type="button">⏸</button>
                                                <button id="btnStepBack" type="button">⏪</button>
                                                <button id="btnStepForward" type="button">⏩</button>
                                                <button id="btnResetTime" type="button">↺</button>
                                            </div>
                                            <label>Velocidad<select id="timeWarp">
                                                <option value="1">x1</option>
                                                <option value="10">x10</option>
                                                <option value="60" selected>x60</option>
                                                <option value="300">x300</option>
                                                <option value="900">x900</option>
                                            </select></label>
                                            <div class="readout">t=<span id="timeLabel">0 s</span> · Elevación=<span id="elevationLabel">--</span> · Pérdida=<span id="lossLabel">--</span></div>
                                        </div>
                                    </section>

                                    <section class="floating-card" id="cardStations">
                                        <header>
                                            <h2>Stations</h2>
                                            <button class="ghost" data-collapse="cardStations">−</button>
                                        </header>
                                        <div class="card-body">
                                            <label>Activa<select id="stationSelect"></select></label>
                                            <div class="button-row">
                                                <button id="btnAddStation" type="button">Añadir</button>
                                                <button id="btnFocusStation" type="button">Enfocar</button>
                                            </div>
                                            <dl class="metrics" id="stationMetrics">
                                                <div><dt>Distancia</dt><dd id="distanceMetric">--</dd></div>
                                                <div><dt>Elevación</dt><dd id="elevationMetric">--</dd></div>
                                                <div><dt>Zenit</dt><dd id="zenithMetric">--</dd></div>
                                                <div><dt>Pérdida geométrica</dt><dd id="lossMetric">--</dd></div>
                                                <div><dt>Doppler</dt><dd id="dopplerMetric">--</dd></div>
                                            </dl>
                                            <div class="mini-chart" id="chartLoss"></div>
                                            <div class="mini-chart" id="chartElevation"></div>
                                            <div class="mini-chart" id="chartDistance"></div>
                                        </div>
                                    </section>
                                    <section class="floating-card" id="cardConstellations">
                                        <header>
                                            <h2>Constellations</h2>
                                            <button class="ghost" data-collapse="cardConstellations">−</button>
                                        </header>
                                        <div class="card-body">
                                            <div class="field-columns">
                                                <label class="field">T (satellites)<input id="walkerT" type="number" min="1" max="2000" value="24" /></label>
                                                <label class="field">P (planes)<input id="walkerP" type="number" min="1" max="200" value="6" /></label>
                                                <label class="field">F (phase)<input id="walkerF" type="number" min="0" max="P-1" value="1" /></label>
                                            </div>
                                            <div class="button-row">
                                                <button id="btnPlotConstellation" type="button">Plot Constellation</button>
                                                <button id="btnClearConstellation" type="button">Clear Constellation</button>
                                            </div>
                                            <div id="constellationControls" class="constellation-controls">
                                                <div id="constellationList"></div>
                                                <div id="constellationStatus" class="hint"></div>
                                            </div>
                                        </div>
                                    </section>
                                </div>
                            </div>
                        </main>
                    </div>

                    <dialog id="stationDialog">
                        <form method="dialog" class="dialog-content">
                            <h2>Nueva estación</h2>
                            <label>Nombre<input id="stationName" required /></label>
                            <label>Latitud (°)<input id="stationLat" type="number" min="-90" max="90" step="0.0001" required /></label>
                            <label>Longitud (°)<input id="stationLon" type="number" min="-180" max="180" step="0.0001" required /></label>
                            <label>Apertura (m)<input id="stationAperture" type="number" min="0.1" max="8" step="0.1" value="1.0" required /></label>
                            <menu>
                                <button value="cancel">Cancelar</button>
                                <button id="stationSave" value="default">Guardar</button>
                            </menu>
                        </form>
                    </dialog>

                    <template id="stationOptionTemplate">
                        <option></option>
                    </template>

                    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
                    <script type="module" src="/static/app.js"></script>
                </body>
                </html>
                """
        ),
}


class QKDApplication:
    """Composes the FastAPI app and exposes the service facade."""

    def __init__(self) -> None:
        self.database = DatabaseGateway(BASE_DIR)
        self.ogs_store = OGSStore(DATA_PATH)
        self.atmosphere = AtmosphereService()
        self.weather = WeatherFieldService()
        self.tles = TleService()
        self.variant_pages = VARIANT_PAGES

        self.app = FastAPI(title="QKD Europe Planner", version="0.2.0")
        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        self._configure_routes()

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _configure_routes(self) -> None:
        app = self.app
        variant_pages = self.variant_pages

        @app.on_event("startup")
        async def _startup() -> None:
            await run_in_threadpool(self.database.initialise)

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            if FAVICON_PATH.exists():
                return FileResponse(str(FAVICON_PATH))
            return Response(status_code=204)

        @app.get("/health")
        async def health() -> Dict[str, str]:
            return {"status": "ok"}

        @app.get("/", response_class=HTMLResponse)
        async def root():
            if not INDEX_HTML.exists():
                return HTMLResponse("index.html not found", status_code=404)
            return FileResponse(str(INDEX_HTML))

        @app.get("/layouts/{variant}", response_class=HTMLResponse)
        async def layout_page(variant: str):
            template = variant_pages.get(variant.lower())
            if template is None:
                raise HTTPException(status_code=404, detail="Layout no disponible.")
            return HTMLResponse(template)

        @app.get("/static/version-{variant}.html", include_in_schema=False)
        async def legacy_layout(variant: str):
            template = variant_pages.get(variant.lower())
            if template is None:
                raise HTTPException(status_code=404, detail="Layout no disponible.")
            return HTMLResponse(template)

        @app.get("/orbit3d", response_class=HTMLResponse)
        async def orbit3d():
            if not ORBIT3D_HTML.exists():
                return HTMLResponse("orbit3d.html not found", status_code=404)
            return FileResponse(str(ORBIT3D_HTML))

        # ------------------- Constellation TLE access ----------------

        @app.get("/api/tles")
        async def list_tle_groups() -> Dict[str, Any]:
            groups = await run_in_threadpool(self.tles.list_groups)
            return {"groups": groups}

        @app.get("/api/tles/{group_id}")
        async def fetch_tle_group(group_id: str):
            try:
                return await run_in_threadpool(self.tles.get_group, group_id)
            except TleGroupNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except TleProviderError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except Exception as exc:  # pylint: disable=broad-except
                raise HTTPException(status_code=500, detail=f"Error inesperado solicitando TLE: {exc}") from exc

        # ------------------- Constellation Analysis with Cosmica ----------------

        @app.post("/api/constellation/analyze")
        async def analyze_constellation(payload: Dict[str, Any]):
            """Analyze a constellation from TLE data using cosmica integration."""
            from . import constellation_manager
            
            constellation_id = payload.get('constellation_id', 'temp')
            tle_list = payload.get('tles', [])
            
            if not tle_list:
                raise HTTPException(status_code=400, detail="No TLE data provided")
            
            manager = constellation_manager.get_constellation_manager()
            
            # Add constellation
            count = await run_in_threadpool(
                manager.add_constellation_from_tle,
                constellation_id,
                tle_list
            )
            
            if count == 0:
                raise HTTPException(status_code=400, detail="No valid TLE data parsed")
            
            # Analyze
            analysis = await run_in_threadpool(
                manager.analyze_constellation,
                constellation_id
            )
            
            if not analysis:
                raise HTTPException(status_code=500, detail="Failed to analyze constellation")
            
            return {
                'constellation_id': constellation_id,
                'parsed_satellites': count,
                'analysis': {
                    'total_satellites': analysis.total_satellites,
                    'operational_satellites': analysis.operational_satellites,
                    'planes': analysis.planes,
                    'mean_altitude_km': analysis.mean_altitude_km,
                    'altitude_range_km': analysis.altitude_range_km,
                    'mean_inclination_deg': analysis.mean_inclination_deg,
                    'inclination_range_deg': analysis.inclination_range_deg,
                    'metadata': analysis.metadata
                }
            }

        @app.post("/api/constellation/propagate")
        async def propagate_constellation(payload: Dict[str, Any]):
            """Propagate constellation over time period."""
            from . import constellation_manager
            
            constellation_id = payload.get('constellation_id')
            start_time_str = payload.get('start_time')
            duration_seconds = payload.get('duration_seconds', 3600)
            time_step = payload.get('time_step_seconds', 60)
            
            if not constellation_id:
                raise HTTPException(status_code=400, detail="constellation_id required")
            
            try:
                if start_time_str:
                    start_time = datetime.fromisoformat(start_time_str.rstrip('Z'))
                else:
                    start_time = datetime.utcnow()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid start_time: {exc}") from exc
            
            manager = constellation_manager.get_constellation_manager()
            
            results = await run_in_threadpool(
                manager.propagate_constellation,
                constellation_id,
                start_time,
                duration_seconds,
                time_step
            )
            
            # Convert to JSON-serializable format
            output = {}
            for sat_name, states in results.items():
                output[sat_name] = [
                    {
                        'timestamp': state.timestamp.isoformat() + 'Z',
                        'latitude': state.latitude,
                        'longitude': state.longitude,
                        'altitude': state.altitude
                    }
                    for state in states
                ]
            
            return {
                'constellation_id': constellation_id,
                'satellites': len(output),
                'samples_per_satellite': len(next(iter(output.values()))) if output else 0,
                'data': output
            }

        @app.get("/api/constellation/{constellation_id}/coverage")
        async def compute_coverage(
            constellation_id: str,
            lat: float,
            lon: float,
            duration_seconds: float = 86400
        ):
            """Compute coverage at a ground location."""
            from . import constellation_manager
            
            manager = constellation_manager.get_constellation_manager()
            
            coverage = await run_in_threadpool(
                manager.compute_coverage_at_location,
                constellation_id,
                lat,
                lon,
                datetime.utcnow(),
                duration_seconds
            )
            
            return coverage

        # ------------------------- OGS management ----------------------

        @app.get("/api/ogs", response_model=List[OGSLocation])
        async def list_ogs():
            raw = await run_in_threadpool(self.ogs_store.list)
            needs_write = False
            processed: List[Dict[str, Any]] = []
            for idx, item in enumerate(raw):
                record = dict(item)
                if "aperture_m" not in record or not isinstance(record["aperture_m"], (int, float)):
                    record["aperture_m"] = 1.0
                    needs_write = True
                if not record.get("id"):
                    record["id"] = f"station-{uuid4().hex[:8]}-{idx}"
                    needs_write = True
                processed.append(record)
            if needs_write:
                await run_in_threadpool(self.ogs_store.overwrite, processed)
            return processed

        @app.post("/api/ogs", response_model=OGSLocation)
        async def add_ogs(loc: OGSLocation):
            if not is_in_europe_bbox(loc.lat, loc.lon):
                raise HTTPException(status_code=400, detail="La ubicacion esta fuera del area de Europa definida.")
            record = await run_in_threadpool(self.ogs_store.upsert, loc.dict())
            return OGSLocation(**record)

        @app.delete("/api/ogs")
        async def clear_ogs():
            await run_in_threadpool(self.ogs_store.delete_all)
            return JSONResponse({"status": "ok", "message": "Todas las OGS han sido eliminadas."})

        @app.delete("/api/ogs/{station_id}")
        async def delete_ogs(station_id: str):
            removed = await run_in_threadpool(self.ogs_store.delete, station_id)
            if not removed:
                raise HTTPException(status_code=404, detail="Estación no encontrada.")
            return JSONResponse({"status": "ok", "deleted": station_id})

        # ---------------------- Atmospheric queries -------------------

        @app.post("/api/get_atmosphere_profile")
        async def get_atmosphere_profile(req: AtmosRequest):
            try:
                target_dt = datetime.fromisoformat(req.time.rstrip('Z'))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Timestamp ISO inválido") from exc
            wavelength = req.wavelength_nm or 810.0
            query = AtmosphereQuery(
                lat=req.lat,
                lon=req.lon,
                timestamp=target_dt,
                model=req.model,
                ground_cn2_day=req.ground_cn2_day,
                ground_cn2_night=req.ground_cn2_night,
                wavelength_nm=wavelength,
            )
            try:
                profile = await run_in_threadpool(self.atmosphere.build_profile, query)
                return profile
            except AtmosphereModelNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except AtmosphereProviderError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except Exception as exc:  # pylint: disable=broad-except
                raise HTTPException(status_code=500, detail=f"Error al procesar atmósfera: {exc}") from exc

        @app.post("/api/get_weather_field")
        async def get_weather_field(req: WeatherFieldRequest):
            try:
                target_dt = datetime.fromisoformat(req.time.rstrip('Z'))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Timestamp ISO inválido") from exc
            query = WeatherFieldQuery(
                timestamp=target_dt,
                variable=req.variable,
                level_hpa=req.level_hpa,
                samples=req.samples,
            )
            try:
                return await run_in_threadpool(self.weather.build_field, query)
            except WeatherFieldParameterError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except AtmosphereProviderError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except Exception as exc:  # pylint: disable=broad-except
                raise HTTPException(status_code=500, detail=f"Error al obtener campo meteorológico: {exc}") from exc

        # ---------------------- Orbital Mechanics API -----------------------

        @app.get("/api/orbital/info")
        async def get_orbital_info():
            """Get information about orbital mechanics capabilities."""
            from . import orbital_mechanics
            return orbital_mechanics.get_orbital_info()

        @app.get("/api/orbital/sun-synchronous")
        async def calculate_sun_sync_orbit(altitude_km: float, eccentricity: float = 0.0):
            """Calculate inclination for sun-synchronous orbit at given altitude."""
            from . import orbital_mechanics
            try:
                inclination = orbital_mechanics.calculate_sun_synchronous_inclination(
                    altitude_km, eccentricity
                )
                elements = orbital_mechanics.OrbitalElements(
                    semi_major_axis=orbital_mechanics.EARTH_RADIUS_KM + altitude_km,
                    eccentricity=eccentricity,
                    inclination=inclination * orbital_mechanics.DEG2RAD,
                    raan=0.0,
                    arg_perigee=0.0,
                    mean_anomaly=0.0
                )
                rates = orbital_mechanics.compute_j2_secular_rates(elements)
                
                return {
                    "altitude_km": altitude_km,
                    "eccentricity": eccentricity,
                    "inclination_deg": inclination,
                    "semi_major_axis_km": elements.semi_major_axis,
                    "period_seconds": elements.period,
                    "raan_drift_deg_per_day": rates.dot_raan * 86400 * orbital_mechanics.RAD2DEG,
                    "is_sun_synchronous": True
                }
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @app.get("/api/orbital/walker-constellation")
        async def generate_walker_constellation(
            T: int,
            P: int, 
            F: int,
            altitude_km: float,
            inclination_deg: float,
            eccentricity: float = 0.0
        ):
            """Generate Walker-Delta constellation parameters."""
            from . import orbital_mechanics
            
            if T <= 0 or P <= 0 or F < 0 or F >= P:
                raise HTTPException(
                    status_code=400, 
                    detail="Invalid Walker parameters. T>0, P>0, 0≤F<P required."
                )
            
            elements_list = orbital_mechanics.calculate_walker_constellation_elements(
                T, P, F, altitude_km, inclination_deg, eccentricity
            )
            
            satellites = []
            for idx, elem in enumerate(elements_list):
                is_valid, error = orbital_mechanics.validate_orbital_elements(elem)
                satellites.append({
                    "id": idx,
                    "semi_major_axis_km": elem.semi_major_axis,
                    "eccentricity": elem.eccentricity,
                    "inclination_deg": elem.inclination * orbital_mechanics.RAD2DEG,
                    "raan_deg": elem.raan * orbital_mechanics.RAD2DEG,
                    "arg_perigee_deg": elem.arg_perigee * orbital_mechanics.RAD2DEG,
                    "mean_anomaly_deg": elem.mean_anomaly * orbital_mechanics.RAD2DEG,
                    "period_seconds": elem.period,
                    "valid": is_valid,
                    "error": error
                })
            
            return {
                "constellation_type": "Walker-Delta",
                "parameters": {"T": T, "P": P, "F": F},
                "altitude_km": altitude_km,
                "inclination_deg": inclination_deg,
                "total_satellites": len(satellites),
                "satellites_per_plane": T // P,
                "satellites": satellites
            }

        @app.get("/api/orbital/repeat-ground-track")
        async def calculate_repeat_ground_track(revolutions_per_day: int):
            """Calculate semi-major axis for repeat ground track orbit."""
            from . import orbital_mechanics
            
            if revolutions_per_day <= 0 or revolutions_per_day > 20:
                raise HTTPException(
                    status_code=400,
                    detail="Revolutions per day must be between 1 and 20"
                )
            
            a, altitude = orbital_mechanics.optimize_semi_major_axis_for_repeat_ground_track(
                revolutions_per_day
            )
            
            return {
                "revolutions_per_day": revolutions_per_day,
                "semi_major_axis_km": a,
                "altitude_km": altitude,
                "period_hours": 24.0 / revolutions_per_day
            }

        # ---------------------- Users and chats -----------------------

        @app.get("/api/users/{user_id}", response_model=UserRead)
        async def fetch_user(user_id: int):
            record = await run_in_threadpool(self.database.get_user_by_id, user_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
            return UserRead(**record.__dict__)

        @app.post("/api/login", response_model=AuthResponse)
        async def login_user(payload: UserCreate):
            try:
                username = _normalize_username(payload.username)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            record = await run_in_threadpool(self.database.verify_credentials, username, payload.password)
            if record is None:
                raise HTTPException(status_code=401, detail="Credenciales incorrectas.")
            return AuthResponse(**record.__dict__, message="Inicio de sesión correcto.")

        @app.post("/api/logout")
        async def logout_user():
            return {"status": "ok", "message": "Sesión cerrada."}

        @app.get("/api/users/count", response_model=UserCount)
        async def user_count():
            count = await run_in_threadpool(self.database.count_users)
            return UserCount(count=count)

        @app.get("/api/chats", response_model=List[ChatRead])
        async def list_chats(limit: int = 50):
            records = await run_in_threadpool(self.database.list_chat_messages, limit)
            return [ChatRead(**record.__dict__) for record in records]

        @app.post("/api/chats", response_model=ChatRead, status_code=201)
        async def post_chat_message(payload: ChatCreate):
            if not payload.message.strip():
                raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
            user = await run_in_threadpool(self.database.get_user_by_id, payload.user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
            record = await run_in_threadpool(self.database.store_chat_message, payload.user_id, payload.message.strip())
            return ChatRead(**record.__dict__)


def create_app() -> FastAPI:
    """Factory for ASGI servers."""
    return QKDApplication().app


# Module level instance for run_app.py compatibility
application = QKDApplication()
app = application.app