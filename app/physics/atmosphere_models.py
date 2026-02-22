# ---------------------------------------------------------------------------
# app/physics/atmosphere_models.py
# ---------------------------------------------------------------------------
# Purpose : Cn² turbulence-profile providers for three models:
#           Hufnagel-Valley 5/7, Bufton, and Greenwood.
#           Each fetches meteorological data from Open-Meteo and builds an
#           ``AtmosphericProfile``.
#
# Functions:
#   hv57_provider(query, client)       – Hufnagel-Valley 5/7
#   bufton_provider(query, client)     – Bufton wind-shear model
#   greenwood_provider(query, client)  – Greenwood frequency model
#
# PROVIDERS dict maps model-name → callable.
#
# Helper (shared):
#   calculate_summary_from_layers(…)   – integrate Cn² → r0, fG, θ₀
#   create_layers_from_samples(…)      – build AtmosphericLayer list
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

from ..services.atmosphere_svc import (
    AtmosphereProviderError,
    AtmosphereQuery,
    AtmosphericLayer,
    AtmosphericProfile,
    AtmosphericSummary,
    OpenMeteoClient,
    resolve_hour_index,
)


# ── Shared helpers ───────────────────────────────────────────────────────

def _calculate_summary(
    layers: Iterable[AtmosphericLayer],
    wavelength_nm: float,
    fallback_wind: Optional[float] = None,
    base_aod: float = 0.2,
    base_abs: float = 0.1,
) -> AtmosphericSummary:
    hm, cn2v, wv = [], [], []
    for L in layers:
        if L.cn2 is None:
            continue
        hm.append(L.alt_km * 1000.0)
        cn2v.append(L.cn2)
        wv.append(L.wind_mps if L.wind_mps is not None else fallback_wind)

    if len(cn2v) < 2:
        return AtmosphericSummary(
            r0_zenith=0.1, fG_zenith=30.0, theta0_zenith=1.5,
            wind_rms=fallback_wind or 15.0,
            loss_aod_db=base_aod, loss_abs_db=base_abs,
        )

    h = np.array(hm)
    cn2 = np.array(cn2v)
    order = np.argsort(h)
    h, cn2 = h[order], cn2[order]
    w = np.array([wv[i] if wv[i] is not None else 0.0 for i in order])

    k = 2.0 * math.pi / (wavelength_nm * 1e-9)
    ir0 = float(np.trapz(cn2, h))
    ith = float(np.trapz(cn2 * h ** (5.0 / 3.0), h))
    iw = float(np.trapz(cn2 * np.abs(w) ** (5.0 / 3.0), h))

    r0 = (0.423 * k ** 2 * max(ir0, 1e-20)) ** (-3.0 / 5.0)
    th0 = (2.91 * k ** 2 * max(ith, 1e-20)) ** (-3.0 / 5.0)
    fG = (0.102 * k ** 2 * max(iw, 1e-30)) ** (3.0 / 5.0)
    wrms = float(np.sqrt(np.mean(w ** 2))) if np.count_nonzero(w) else (fallback_wind or 15.0)
    tau0 = 0.314 * r0 / max(wrms, 1e-3)
    cs = max(ir0, 1e-12)

    return AtmosphericSummary(
        r0_zenith=float(r0),
        fG_zenith=float(fG),
        theta0_zenith=float(math.degrees(th0) * 3600.0),
        wind_rms=float(wrms),
        loss_aod_db=float(base_aod + min(1.8, 0.18 * cs ** 0.3)),
        loss_abs_db=float(base_abs + min(1.2, 0.12 * cs ** 0.25)),
        coherence_time_ms=float(tau0 * 1e3),
    )


def _make_layers(
    alts: Sequence[float],
    cn2_fn: Callable[[float], float],
    wind_fn: Callable[[float], float],
    temp_fn: Optional[Callable[[float], Optional[float]]] = None,
) -> List[AtmosphericLayer]:
    return [
        AtmosphericLayer(
            alt_km=a,
            cn2=float(cn2_fn(a * 1000.0)),
            wind_mps=float(wind_fn(a)),
            temperature_k=temp_fn(a) if temp_fn else None,
        )
        for a in alts
    ]


def _wind_speed_from_hourly(
    hourly: Dict[str, Any], key: str, idx: int
) -> float:
    u = hourly.get(f"wind_u_component_{key}", [None])[idx]
    v = hourly.get(f"wind_v_component_{key}", [None])[idx]
    if u is None or v is None:
        raise AtmosphereProviderError(f"Missing wind for {key}")
    return float(math.sqrt(u ** 2 + v ** 2))


# ── Hufnagel-Valley 5/7 ─────────────────────────────────────────────────

def hv57_provider(q: AtmosphereQuery, c: OpenMeteoClient) -> AtmosphericProfile:
    vs = ["wind_u_component_300hPa", "wind_v_component_300hPa"]
    ds = c.fetch_hourly(q, vs)
    hr = ds["hourly"]
    ix = resolve_hour_index(hr, q.hour_key)
    W = _wind_speed_from_hourly(hr, "300hPa", ix)
    W = max(W, 5.0)
    A = max(q.ground_cn2, 1e-17)

    def cn2(h: float) -> float:
        t1 = 0.00594 * (W / 27.0) ** 2 * (h * 1e-5) ** 10 * math.exp(-h / 1000)
        return t1 + 2.7e-16 * math.exp(-h / 1500) + A * math.exp(-h / 100)

    alt = (0.0, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0)
    wfn = lambda a: max(0.0, W * (1.0 - math.exp(-a / 5.0)) + 3.0)
    layers = _make_layers(alt, cn2, wfn)
    summary = _calculate_summary(layers, q.wavelength_nm, fallback_wind=W)
    ts = q.timestamp.replace(microsecond=0).isoformat() + "Z"
    return AtmosphericProfile(
        model="hufnagel-valley", status="ok", timestamp=ts,
        summary=summary, layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": vs},
        metadata={"daytime": q.is_day, "wavelength_nm": q.wavelength_nm,
                  "ground_cn2": q.ground_cn2, "wind_speed_300hPa": W},
    )


# ── Bufton ───────────────────────────────────────────────────────────────

def bufton_provider(q: AtmosphereQuery, c: OpenMeteoClient) -> AtmosphericProfile:
    vs = [
        "wind_u_component_300hPa", "wind_v_component_300hPa",
        "wind_u_component_500hPa", "wind_v_component_500hPa",
        "wind_u_component_850hPa", "wind_v_component_850hPa",
        "temperature_850hPa",
    ]
    ds = c.fetch_hourly(q, vs)
    hr = ds["hourly"]
    ix = resolve_hour_index(hr, q.hour_key)
    w300 = _wind_speed_from_hourly(hr, "300hPa", ix)
    w500 = _wind_speed_from_hourly(hr, "500hPa", ix)
    w850 = _wind_speed_from_hourly(hr, "850hPa", ix)
    t850 = hr.get("temperature_850hPa", [None])[ix]
    lc = 0.8 if t850 is None else max(0.5, min(1.5, (t850 + 273.15) / 290.0))
    A = max(q.ground_cn2, 1e-17)
    sf = max(0.5, min(2.5, abs(w500 - w850) / 10.0))

    def cn2(h: float) -> float:
        hk = h / 1000.0
        if hk < 0.5:
            return A * math.exp(-h / 60)
        if hk < 1.5:
            return 0.3 * A * math.exp(-h / 120) * sf
        if hk < 5.0:
            return 0.08 * A * math.exp(-h / 600) * lc
        return 0.02 * A * math.exp(-(h - 5000) / 1500)

    def wfn(a: float) -> float:
        if a < 0.5:
            return max(2.0, w850 * 0.6)
        if a < 1.5:
            return (w850 + w500) / 2
        if a < 6:
            return w500
        return w300

    def tfn(a: float):
        if t850 is None:
            return None
        return float((t850 + 273.15) + (-6.5) * (a - 1.5))

    alt = (0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0)
    layers = _make_layers(alt, cn2, wfn, tfn)
    fw = float(np.sqrt((w300**2 + w500**2 + w850**2) / 3.0))
    summary = _calculate_summary(layers, q.wavelength_nm, fw, 0.25, 0.12)
    summary.scintillation_index = float(min(1.5, 0.3 + sf * 0.2))
    ts = q.timestamp.replace(microsecond=0).isoformat() + "Z"
    return AtmosphericProfile(
        model="bufton", status="ok", timestamp=ts,
        summary=summary, layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": vs},
        metadata={"daytime": q.is_day, "wavelength_nm": q.wavelength_nm,
                  "ground_cn2": q.ground_cn2,
                  "wind_speed_300hPa": w300,
                  "wind_speed_500hPa": w500,
                  "wind_speed_850hPa": w850},
    )


# ── Greenwood ────────────────────────────────────────────────────────────

def greenwood_provider(q: AtmosphereQuery, c: OpenMeteoClient) -> AtmosphericProfile:
    vs = [
        "wind_u_component_300hPa", "wind_v_component_300hPa",
        "wind_u_component_500hPa", "wind_v_component_500hPa",
        "wind_u_component_700hPa", "wind_v_component_700hPa",
    ]
    ds = c.fetch_hourly(q, vs)
    hr = ds["hourly"]
    ix = resolve_hour_index(hr, q.hour_key)
    w300 = _wind_speed_from_hourly(hr, "300hPa", ix)
    w500 = _wind_speed_from_hourly(hr, "500hPa", ix)
    w700 = _wind_speed_from_hourly(hr, "700hPa", ix)
    A = max(q.ground_cn2, 1e-17)

    def cn2(h: float) -> float:
        hk = h / 1000.0
        if hk < 0.5:
            return A * math.exp(-h / 50)
        if hk < 2.0:
            return 0.2 * A * math.exp(-h / 200)
        if hk < 8.0:
            return 0.05 * A * math.exp(-h / 900)
        return 0.02 * A * math.exp(-(h - 8000) / 1500)

    def wfn(a: float) -> float:
        if a < 1.5:
            return (w700 + w500) / 2
        if a < 5:
            return (w500 + w300) / 2
        return w300

    alt = (0.0, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0)
    layers = _make_layers(alt, cn2, wfn)
    fw = float((w300 + w500 + w700) / 3.0)
    summary = _calculate_summary(layers, q.wavelength_nm, fw, 0.22, 0.11)
    ts = q.timestamp.replace(microsecond=0).isoformat() + "Z"
    return AtmosphericProfile(
        model="greenwood", status="ok", timestamp=ts,
        summary=summary, layers=layers,
        sources={"provider": "Open-Meteo forecast", "variables": vs},
        metadata={"daytime": q.is_day, "wavelength_nm": q.wavelength_nm,
                  "ground_cn2": q.ground_cn2,
                  "wind_speed_300hPa": w300,
                  "wind_speed_500hPa": w500,
                  "wind_speed_700hPa": w700},
    )


# ── Registry ─────────────────────────────────────────────────────────────

PROVIDERS: Dict[str, Callable] = {
    "hufnagel-valley": hv57_provider,
    "hv57": hv57_provider,
    "bufton": bufton_provider,
    "greenwood": greenwood_provider,
}
