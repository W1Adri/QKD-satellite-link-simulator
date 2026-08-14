# ---------------------------------------------------------------------------
# app/routers/paper.py
# ---------------------------------------------------------------------------
# Paper-reproduction endpoints for:
#
#   Ntanos, Lyras, Zavitsanos, Giannoulis, Panagopoulos, Avramopoulos,
#   "LEO Satellites Constellation-to-Ground QKD Links: Greek Quantum
#    Communication Infrastructure Paradigm", Photonics 2021, 8, 544.
#
# Reproduces the paper's decoy-state BB84 downlink results (Fig. 2, 3, 5, 6, 7
# and Table 1) using the paper-mode physics variants:
#   - Gaussian transmit/receive gains + free-space loss  (Eq. 3, 5, 6)
#   - beta-distributed pointing loss at outage p0         (Eq. 8-10)
#   - modified Hufnagel-Valley Cn^2 with OGS altitude      (Eq. 11)
#   - scintillation loss (Rytov + aperture averaging)      (Eq. 12-18)
#   - background solar radiance                            (Eq. 19-20)
#   - weak+vacuum decoy-state SKR/pulse (q from Eq. A1)    (Eq. 1, A1-A6)
#
# All heavy lifting reuses the verified pure-NumPy physics layer in
# app/physics/.  Endpoints are read-only (no persistence).
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..physics.atmosphere_models import modified_hv_layers
from ..physics.geometry import compute_station_metrics
from ..physics.propagation import propagate_orbit
from ..physics.qkd import calculate_bb84_decoy
from ..physics.walker import sun_synchronous_inclination

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/paper", tags=["paper"])

EARTH_RADIUS_KM = 6378.137

# ── Canonical paper parameters (Section 4.1) ──────────────────────────────
# "literal-first": paper values where stated; documented assumptions otherwise.
PAPER: Dict[str, Any] = {
    "wavelength_nm": 1550.0,
    "sat_aperture_m": 0.15,          # Tx aperture (all 3 satellites) → ~13 µrad
    "sigma_p_urad": 0.75,            # pointing error variance
    "p0": 0.01,                      # outage probability (pointing + scintillation)
    "min_elevation_deg": 20.0,
    "ground_cn2": 1.7e-14,           # A0 at sea level (m^-2/3)
    "u_rms": 10.0,                   # average wind speed (Bufton), m/s
    "fov_half_mrad": 0.05,           # FOV 100 µrad full-angle → 50 µrad half
    "filter_nm": 0.2,                # band-pass filter width
    "detector_efficiency": 0.85,     # SNSPD @ 1550 nm
    "dark_count_rate": 300.0,        # cps
    "gate_time_s": 1e-9,             # detector gate 1 ns
    # fixed receiver-side loss (excl. detector QE): Bob 2.65 + filter 3 + pol 0.3
    "fixed_optics_loss_db": 2.65 + 3.0 + 0.3,
    # zenith atmospheric transmittance loss — NOT given in the paper (ITU-R [46]);
    # documented assumption ≈0.5 dB at 1550 nm clear sky (dominated by geometry).
    "atm_zenith_loss_db": 0.5,
    "mu_signal": 0.56,               # signal mean photon number
    "mu_decoy": 0.11,                # decoy mean photon number
    # protocol efficiency q — Eq. A1 with signal:decoy:vacuum = 4:1:16 gives
    # q = (1/2)·4/21 = 2/21 ≈ 0.0952.  Section 4.1 states "q = 2/5", which is
    # inconsistent with Eq. A1 (apparent typo); the Eq.-A1 value reproduces the
    # reported SKR magnitudes and inter-station ratios, so we use it.
    "q": 0.5 * 4.0 / (4.0 + 1.0 + 16.0),
    "f_ec": 1.22,                    # CASCADE error-correction efficiency f(e)
    "e_optical": 0.01,               # baseline QBER e_det = (1-V)/2, V=0.98
    "f_rep": 1e8,                    # 100 MHz pulse repetition rate
    "Hrad_night": 1.5e-4,            # nighttime radiance W/(sr·m²·µm)
    "altitude_km": 600.0,
    "inclination_deg": 97.4,         # sun-synchronous
}

# Greek optical ground stations (Ntanos 2021).  lat/lon corrected (the paper
# text swaps the two columns).  aperture = receiver telescope diameter.
STATIONS: List[Dict[str, Any]] = [
    {"id": "helmos", "name": "Helmos", "lat": 37.9844, "lon": 22.1961,
     "altitude_m": 2340.0, "aperture_m": 2.3},
    {"id": "skinakas", "name": "Skinakas", "lat": 35.212, "lon": 24.899,
     "altitude_m": 1750.0, "aperture_m": 1.3},
    {"id": "cholomondas", "name": "Cholomondas", "lat": 40.3419, "lon": 23.506,
     "altitude_m": 850.0, "aperture_m": 0.75},
]


# ── Geometry helpers ──────────────────────────────────────────────────────

def _slant_km(elev_deg: float, H_km: float) -> float:
    """Slant range (km) for an elevation angle and orbit altitude (Ntanos Eq. 4)."""
    e = math.radians(elev_deg)
    Re = EARTH_RADIUS_KM
    return Re * (math.sqrt(((H_km + Re) / Re) ** 2 - math.cos(e) ** 2) - math.sin(e))


def _elev_from_slant(d_km: float, H_km: float) -> float:
    """Invert Eq. 4: elevation angle (deg) for a slant range and orbit altitude."""
    Re = EARTH_RADIUS_KM
    # law of cosines in the Earth-centre triangle
    r_sat = Re + H_km
    cos_zen = (r_sat ** 2 - Re ** 2 - d_km ** 2) / (2.0 * Re * d_km)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.acos(cos_zen)            # local zenith angle at OGS
    return max(0.0, 90.0 - math.degrees(zenith))


def _cn2_layers(h_gs_m: float) -> List[tuple]:
    return modified_hv_layers(
        h_gs_m=h_gs_m, ground_cn2=PAPER["ground_cn2"], u_rms=PAPER["u_rms"],
    )


def _background_cps(hrad: float, aperture_m: float) -> float:
    from ..physics.link_budget import background_noise_cps
    return background_noise_cps(
        hrad, PAPER["fov_half_mrad"], aperture_m,
        PAPER["filter_nm"], PAPER["wavelength_nm"],
    )


def _link_loss_db(
    elev_deg: float,
    distance_km: float,
    aperture_m: float,
    h_gs_m: float,
    cn2_layers: List[tuple],
) -> float:
    """Total optical channel loss (dB, excl. detector QE) using paper variants."""
    from ..physics.geometry import geometric_loss
    from ..physics.link_budget import (
        atm_loss_db, pointing_loss_beta_db, scintillation_loss_db,
    )
    lam = PAPER["wavelength_nm"]
    geo = geometric_loss(
        distance_km, PAPER["sat_aperture_m"], aperture_m, lam, model="gaussian",
    )["lossDb"]
    atm = atm_loss_db(elev_deg, PAPER["atm_zenith_loss_db"], 0.0)
    w0 = 2.0 * (lam * 1e-9) / (math.pi * PAPER["sat_aperture_m"])
    ptg = pointing_loss_beta_db(PAPER["sigma_p_urad"], w0, PAPER["p0"])
    sci = scintillation_loss_db(
        elev_deg, lam, aperture_m, cn2_layers=cn2_layers, p0=PAPER["p0"],
        link_direction="downlink", H_sat_m=PAPER["altitude_km"] * 1000.0,
        h_gs=h_gs_m,
    )
    return geo + atm + ptg + sci + PAPER["fixed_optics_loss_db"]


def _skr_per_pulse(loss_db: float, bg_cps: float) -> Dict[str, float]:
    """Decoy-state BB84 SKR/pulse (bits/pulse) and QBER for a channel loss."""
    r = calculate_bb84_decoy({
        "photonRate": PAPER["f_rep"],
        "channelLossdB": loss_db,
        "detectorEfficiency": PAPER["detector_efficiency"],
        "darkCountRate": PAPER["dark_count_rate"],
        "backgroundCps": bg_cps,
        "mu_signal": PAPER["mu_signal"],
        "mu_decoy": PAPER["mu_decoy"],
        "e_optical": PAPER["e_optical"],
        "q": PAPER["q"],
        "f_ec": PAPER["f_ec"],
        "paper_noise": True,
        "gate_time_s": PAPER["gate_time_s"],
    })
    return {
        "skrPerPulse": max(0.0, r.get("secureKeyRatePerPulse", 0.0)),
        "qber": r.get("qber", 0.0),
    }


def _link_budget_cfg(hrad: float) -> Dict[str, Any]:
    return {
        "pointing_error_urad": PAPER["sigma_p_urad"],
        "atm_zenith_aod_db": PAPER["atm_zenith_loss_db"],
        "atm_zenith_abs_db": 0.0,
        "fixed_optics_loss_db": PAPER["fixed_optics_loss_db"],
        "scintillation_enabled": True,
        "scintillation_p0": PAPER["p0"],
        "background_enabled": True,
        "background_Hrad_W_m2_sr_um": hrad,
        "background_fov_mrad": PAPER["fov_half_mrad"],
        "background_delta_lambda_nm": PAPER["filter_nm"],
        "min_elevation_deg": PAPER["min_elevation_deg"],
        "geometric_model": "gaussian",
        "pointing_model": "beta",
    }


def _is_night(epoch_iso: str, t_s: float, lon_deg: float) -> bool:
    """Paper day/night filter: daylight = 06:00-18:00 local solar time.

    Delegates the window test to ``physics.availability.is_night_local_solar``
    so the pass filter and the night-conditioned cloud statistic can never
    diverge — a night-only key integral weighted by an all-hours PCFLOS is the
    wrong conditional probability.
    """
    from ..physics.availability import is_night_local_solar
    try:
        base = datetime.fromisoformat(epoch_iso.replace("Z", "+00:00"))
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
    except Exception:
        base = datetime(2024, 3, 20, tzinfo=timezone.utc)
    utc_hours = (base.timestamp() + t_s) / 3600.0
    return is_night_local_solar(utc_hours, lon_deg)


# ── Request models ────────────────────────────────────────────────────────

class LinkSweepRequest(BaseModel):
    distance_min_km: float = 300.0
    distance_max_km: float = 1500.0
    distance_steps: int = Field(default=40, ge=2, le=200)
    aperture_min_m: float = 0.5
    aperture_max_m: float = 2.5
    aperture_steps: int = Field(default=40, ge=2, le=200)
    elevation_deg: float = 90.0                # Fig. 2 sweeps at zenith
    h_gs_m: float = 0.0                         # generic (sea-level) turbulence
    hrad: Optional[float] = None                # default: nighttime radiance


class RadianceSweepRequest(BaseModel):
    x_axis: str = "distance"                    # "distance" (Fig 3a) | "elevation" (Fig 3b)
    radiance_min: float = 0.0
    radiance_max: float = 0.1
    radiance_steps: int = Field(default=40, ge=2, le=200)
    x_min: float = 300.0                        # km (distance) or deg (elevation)
    x_max: float = 1000.0
    x_steps: int = Field(default=40, ge=2, le=200)
    aperture_m: float = 0.75
    h_gs_m: float = 0.0
    altitude_km: float = 600.0                  # for elevation→distance mapping


class SinglePassRequest(BaseModel):
    station_id: str = "helmos"
    ltan_hours: float = 22.0                    # night pass
    epoch: str = "2024-03-20T00:00:00Z"
    total_orbits: int = Field(default=16, ge=1, le=60)
    samples_per_orbit: int = Field(default=240, ge=30, le=1000)


class ConstellationRequest(BaseModel):
    n_sats: int = Field(default=10, ge=1, le=20)
    station_ids: Optional[List[str]] = None     # default: all 3 Greek OGS
    epoch: str = "2024-03-20T00:00:00Z"
    # ~10 days: per-sat yearly key converges by ~16 days, so this window scaled
    # to a year is stable (see REPRODUCTION report). Increase for smoother Fig 6/7.
    total_orbits: int = Field(default=150, ge=1, le=800)
    samples_per_orbit: int = Field(default=45, ge=20, le=600)
    nighttime_only: bool = True

    # ── Cloud availability (PCFLOS) ─────────────────────────────────────────
    # Off by default so `totals_gbit_year` stays the clear-sky number that is
    # comparable to Ntanos et al. 2021 Table 1 ("no link interruption due to
    # clouds").  When on, the cloud-weighted totals arrive in SEPARATE keys —
    # the two must never be confounded, especially given the known ~7x annual
    # discrepancy already documented for that reproduction.
    availability_enabled: bool = False
    cloud_aspect_ratio: float = Field(default=1.0, ge=0.0, le=5.0)
    cloud_night_only: bool = True          # matches nighttime_only by default
    cloud_year: Optional[int] = None       # None → epoch year − 1
    # {station_id: {"time": [...], "cloud_cover": [...]}} — supplying this keeps
    # the run offline and reproducible.  Stations absent from the map are
    # fetched from the ERA5 archive; a failed fetch is reported, not assumed.
    cloud_cover_hourly: Optional[Dict[str, Dict[str, Any]]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/preset")
def get_preset() -> Dict[str, Any]:
    """Canonical paper parameters + Greek OGS (for UI display / inspection)."""
    return {"params": PAPER, "stations": STATIONS,
            "reference": "Ntanos et al., Photonics 2021, 8, 544"}


@router.post("/link-sweep")
async def link_sweep(req: LinkSweepRequest) -> Dict[str, Any]:
    """Fig. 2: total downlink loss (dB) and SKR/pulse over distance × aperture."""
    return await run_in_threadpool(_run_link_sweep, req)


def _run_link_sweep(req: LinkSweepRequest) -> Dict[str, Any]:
    hrad = PAPER["Hrad_night"] if req.hrad is None else req.hrad
    dists = _linspace(req.distance_min_km, req.distance_max_km, req.distance_steps)
    aps = _linspace(req.aperture_min_m, req.aperture_max_m, req.aperture_steps)
    cn2 = _cn2_layers(req.h_gs_m)
    loss_grid: List[List[float]] = []
    skr_grid: List[List[float]] = []
    for d in dists:
        loss_row, skr_row = [], []
        for ap in aps:
            loss = _link_loss_db(req.elevation_deg, d, ap, req.h_gs_m, cn2)
            bg = _background_cps(hrad, ap)
            loss_row.append(round(loss, 4))
            skr_row.append(_skr_per_pulse(loss, bg)["skrPerPulse"])
        loss_grid.append(loss_row)
        skr_grid.append(skr_row)
    return {
        "distances_km": dists, "apertures_m": aps,
        "lossDb": loss_grid, "skrPerPulse": skr_grid,
        "elevation_deg": req.elevation_deg, "hrad": hrad,
    }


@router.post("/radiance-sweep")
async def radiance_sweep(req: RadianceSweepRequest) -> Dict[str, Any]:
    """Fig. 3: SKR/pulse over solar radiance × (distance | elevation)."""
    return await run_in_threadpool(_run_radiance_sweep, req)


def _run_radiance_sweep(req: RadianceSweepRequest) -> Dict[str, Any]:
    rads = _linspace(req.radiance_min, req.radiance_max, req.radiance_steps)
    xs = _linspace(req.x_min, req.x_max, req.x_steps)
    cn2 = _cn2_layers(req.h_gs_m)
    skr_grid: List[List[float]] = []
    for hrad in rads:
        row = []
        bg = _background_cps(hrad, req.aperture_m)
        for x in xs:
            if req.x_axis == "elevation":
                elev = x
                dist = _slant_km(elev, req.altitude_km)
            else:  # distance
                elev = 90.0
                dist = x
            loss = _link_loss_db(elev, dist, req.aperture_m, req.h_gs_m, cn2)
            row.append(_skr_per_pulse(loss, bg)["skrPerPulse"])
        skr_grid.append(row)
    return {
        "radiances": rads, "x_axis": req.x_axis, "x_values": xs,
        "skrPerPulse": skr_grid, "aperture_m": req.aperture_m,
    }


@router.post("/single-pass")
async def single_pass(req: SinglePassRequest) -> Dict[str, Any]:
    """Fig. 5: SKR/pulse and slant distance vs. time for one satellite pass."""
    return await run_in_threadpool(_run_single_pass, req)


def _sso_elements(ltan_hours: float, epoch: str) -> Dict[str, float]:
    from ..physics.walker import ltan_to_raan
    alt = PAPER["altitude_km"]
    inc = sun_synchronous_inclination(alt)
    raan = ltan_to_raan(ltan_hours, epoch)
    return {
        "a": EARTH_RADIUS_KM + alt, "e": 0.0, "inc": inc,
        "raan": raan, "argpe": 0.0, "M0": 0.0,
    }


def _propagate(elements: Dict[str, float], epoch: str,
               total_orbits: int, samples_per_orbit: int) -> Dict[str, Any]:
    """Propagate one SSO orbit (J2) — shared across stations for a satellite."""
    return propagate_orbit(
        a=elements["a"], e=elements["e"], inc_deg=elements["inc"],
        raan_deg=elements["raan"], arg_pe_deg=elements["argpe"],
        M0_deg=elements["M0"], j2_enabled=True, epoch_iso=epoch,
        samples_per_orbit=samples_per_orbit, total_orbits=total_orbits,
    )


def _score(prop: Dict[str, Any], station: Dict[str, Any], hrad: float,
           epoch: str) -> Dict[str, Any]:
    """Compute paper-mode metrics + SKR/pulse per sample for one station."""
    optics = {
        "satAperture": PAPER["sat_aperture_m"],
        "groundAperture": station["aperture_m"],
        "wavelength": PAPER["wavelength_nm"],
    }
    metrics = compute_station_metrics(
        prop["data_points"],
        {"lat": station["lat"], "lon": station["lon"],
         "altitude_m": station["altitude_m"]},
        optics, None,
        link_budget_cfg=_link_budget_cfg(hrad),
        cn2_layers=_cn2_layers(station["altitude_m"]),
        link_direction="downlink", epoch_iso=epoch,
    )
    timeline = prop["timeline"]
    n = len(timeline)
    skr_pp = [0.0] * n
    for i in range(n):
        elev = metrics["elevationDeg"][i]
        if elev is None or elev < PAPER["min_elevation_deg"]:
            continue
        if not metrics["linkEstablished"][i]:
            continue
        skr_pp[i] = _skr_per_pulse(
            metrics["lossDb"][i], metrics["backgroundCps"][i])["skrPerPulse"]
    return {"timeline": timeline, "elev": metrics["elevationDeg"],
            "dist": metrics["distanceKm"], "skr_pp": skr_pp}


def _propagate_and_score(
    elements: Dict[str, float], station: Dict[str, Any], hrad: float,
    epoch: str, total_orbits: int, samples_per_orbit: int,
) -> Dict[str, Any]:
    """Convenience: propagate one orbit and score a single station."""
    prop = _propagate(elements, epoch, total_orbits, samples_per_orbit)
    return _score(prop, station, hrad, epoch)


def _extract_best_pass(scored: Dict[str, Any]) -> Dict[str, Any]:
    """Return the contiguous elev>threshold pass containing the peak elevation."""
    elev = scored["elev"]
    n = len(elev)
    thr = PAPER["min_elevation_deg"]
    peak_i = max(
        (i for i in range(n) if elev[i] is not None and elev[i] >= thr),
        key=lambda i: elev[i], default=None,
    )
    if peak_i is None:
        return {"t": [], "skrPerPulse": [], "distanceKm": [], "elevationDeg": [],
                "duration_s": 0.0, "max_skr_per_pulse": 0.0, "max_elevation_deg": 0.0,
                "total_key_bits": 0.0}
    lo = peak_i
    while lo > 0 and elev[lo - 1] is not None and elev[lo - 1] >= thr:
        lo -= 1
    hi = peak_i
    while hi < n - 1 and elev[hi + 1] is not None and elev[hi + 1] >= thr:
        hi += 1
    t = scored["timeline"][lo:hi + 1]
    skr = scored["skr_pp"][lo:hi + 1]
    dist = scored["dist"][lo:hi + 1]
    el = scored["elev"][lo:hi + 1]
    t0 = t[0]
    t_rel = [round(x - t0, 3) for x in t]
    # integrate distilled key bits over the pass:  ∫ SKR/pulse · f_rep dt
    total_bits = 0.0
    for k in range(len(t) - 1):
        dt = t[k + 1] - t[k]
        rate0 = skr[k] * PAPER["f_rep"]
        rate1 = skr[k + 1] * PAPER["f_rep"]
        total_bits += 0.5 * (rate0 + rate1) * dt
    return {
        "t": t_rel, "skrPerPulse": skr, "distanceKm": dist, "elevationDeg": el,
        "duration_s": round(t[-1] - t[0], 1),
        "max_skr_per_pulse": max(skr) if skr else 0.0,
        "max_elevation_deg": round(max(x for x in el if x is not None), 2),
        "total_key_bits": total_bits,
    }


def _run_single_pass(req: SinglePassRequest) -> Dict[str, Any]:
    station = _get_station(req.station_id)
    elements = _sso_elements(req.ltan_hours, req.epoch)
    scored = _propagate_and_score(
        elements, station, PAPER["Hrad_night"], req.epoch,
        req.total_orbits, req.samples_per_orbit,
    )
    best = _extract_best_pass(scored)
    best["station"] = station
    best["total_key_Mbit"] = round(best["total_key_bits"] / 1e6, 4)
    return best


@router.post("/constellation")
async def constellation(req: ConstellationRequest) -> Dict[str, Any]:
    """Fig. 6/7 + Table 1: SKR/pulse over time and yearly distilled key per OGS."""
    return await run_in_threadpool(_run_constellation, req)


def _availability_profiles(
    req: ConstellationRequest,
    stations: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Per-station PCFLOS(elevation) profiles for the annual constellation run.

    Returns ``(profiles, report, notes)``.  Each profile is the DAY-WEIGHTED
    MEAN of the twelve monthly profiles: the simulation window is only 4-10 days
    and its result is then scaled to a year, so using the single month the
    window falls in would extrapolate (say) March cloud statistics to all twelve
    months.  Averaging over the calendar with day weights is the expectation
    over a year of recurring passes, and it reduces exactly to the current
    behaviour when every factor is 1.
    """
    from ..physics.availability import monthly_cover_stats, pcflos_profile_annual

    injected = req.cloud_cover_hourly or {}
    year = req.cloud_year
    if year is None:
        try:
            year = int((req.epoch or "")[:4]) - 1
        except (TypeError, ValueError):
            year = 2024

    profiles: Dict[str, Any] = {}
    report: Dict[str, Any] = {}
    notes: List[str] = []
    for st in stations:
        sid = st["id"]
        hourly = injected.get(sid)
        if not hourly:
            try:
                from ..services.pcflos_svc import fetch_hourly_cover
                hourly = fetch_hourly_cover(st["lat"], st["lon"], year)
            except Exception as exc:
                notes.append(
                    f"{sid}: no cloud data (year {year}) — "
                    f"{type(exc).__name__}: {exc}; availability factor 1.0"
                )
                continue
        stats = monthly_cover_stats(
            hourly, night_only=bool(req.cloud_night_only), lon_deg=st["lon"])
        if not stats.get("valid_hours"):
            notes.append(f"{sid}: cloud series has no valid hours; factor 1.0")
            continue
        prof = pcflos_profile_annual(
            stats, beta=float(req.cloud_aspect_ratio))
        profiles[sid] = prof
        report[sid] = {
            "zenith_annual": round(prof["zenith"], 5),
            "monthly_zenith": {m: round(v, 5)
                               for m, v in prof["monthly_zenith"].items()},
            "mean_cover_annual": round(stats["mean_cover_annual"], 5),
            "valid_hours": stats["valid_hours"],
            "source": "injected" if injected.get(sid) else "archive",
        }
    return profiles, report, notes


def _run_constellation(req: ConstellationRequest) -> Dict[str, Any]:
    station_ids = req.station_ids or [s["id"] for s in STATIONS]
    stations = [_get_station(sid) for sid in station_ids]
    # Spread the constellation across LTAN (≈ RAAN / local pass time) so passes
    # do not overlap — the paper places sats for maximum availability.
    ltans = [ (i * 24.0 / req.n_sats) for i in range(req.n_sats) ]
    epoch = req.epoch
    window_s = req.total_orbits * _orbit_period_s()
    year_scale = (365.25 * 86400.0) / window_s

    profiles: Dict[str, Any] = {}
    av_report: Dict[str, Any] = {}
    av_notes: List[str] = []
    if req.availability_enabled:
        profiles, av_report, av_notes = _availability_profiles(req, stations)

    # series[station_id] = list of {sat, t[], skrPerPulse[]}
    series: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in stations}
    table: Dict[str, Dict[str, float]] = {s["id"]: {} for s in stations}
    table_av: Dict[str, Dict[str, float]] = {s["id"]: {} for s in stations}

    for si in range(req.n_sats):
        elements = _sso_elements(ltans[si], epoch)
        prop = _propagate(elements, epoch, req.total_orbits, req.samples_per_orbit)
        for st in stations:
            scored = _score(prop, st, PAPER["Hrad_night"], epoch)
            t = scored["timeline"]
            skr = list(scored["skr_pp"])
            # Nighttime filter (paper: daylight 06:00-18:00 local → no key)
            if req.nighttime_only:
                for i in range(len(t)):
                    if skr[i] > 0 and not _is_night(epoch, t[i], st["lon"]):
                        skr[i] = 0.0
            # Per-sample availability, so the cloud factor sits INSIDE the time
            # integral.  That matters: high-elevation samples are both more
            # likely to be clear and more productive, so a pass-mean factor
            # pulled outside the integral would drop a positive covariance.
            prof = profiles.get(st["id"])
            avail = None
            if prof is not None:
                from ..physics.availability import profile_at
                elev = scored["elev"]
                avail = [profile_at(prof, e) for e in elev]
            # integrate distilled bits over the window
            bits = 0.0
            bits_av = 0.0
            for k in range(len(t) - 1):
                dt = t[k + 1] - t[k]
                bits += 0.5 * (skr[k] + skr[k + 1]) * PAPER["f_rep"] * dt
                if avail is not None:
                    bits_av += 0.5 * (skr[k] * avail[k]
                                      + skr[k + 1] * avail[k + 1]) \
                               * PAPER["f_rep"] * dt
            gbit_year = bits * year_scale / 1e9
            table[st["id"]][f"sat{si + 1}"] = round(gbit_year, 4)
            if avail is not None:
                table_av[st["id"]][f"sat{si + 1}"] = round(
                    bits_av * year_scale / 1e9, 4)
            # keep a decimated time series for plotting (skip empty)
            if any(v > 0 for v in skr):
                series[st["id"]].append({
                    "sat": f"sat{si + 1}",
                    "t_hours": [round(x / 3600.0, 4) for x in t],
                    "skrPerPulse": skr,
                })

    # per-station totals and peak SKR
    totals: Dict[str, float] = {}
    totals_av: Dict[str, float] = {}
    peak: Dict[str, float] = {}
    for st in stations:
        vals = table[st["id"]]
        totals[st["id"]] = round(sum(vals.values()), 4)
        if table_av[st["id"]]:
            totals_av[st["id"]] = round(sum(table_av[st["id"]].values()), 4)
        ps = [max(s["skrPerPulse"]) for s in series[st["id"]] if s["skrPerPulse"]]
        peak[st["id"]] = max(ps) if ps else 0.0

    out = {
        "stations": {s["id"]: {"name": s["name"], "aperture_m": s["aperture_m"],
                               "altitude_m": s["altitude_m"]} for s in stations},
        "table_gbit_year": table,
        "totals_gbit_year": totals,
        "peak_skr_per_pulse": peak,
        "series": series,
        "meta": {
            "n_sats": req.n_sats, "window_orbits": req.total_orbits,
            "window_days": round(window_s / 86400.0, 3),
            "year_scale": round(year_scale, 2),
            "nighttime_only": req.nighttime_only,
            "note": "Yearly key = window integral × (year / window); ephemerides "
                    "are self-generated SSO (STK data in the paper is not public).",
        },
    }

    if req.availability_enabled:
        # SEPARATE keys, never folded into totals_gbit_year: Ntanos et al. 2021
        # Table 1 is explicitly cloud-free, so a PCFLOS-weighted total is not
        # comparable to their Gbit/year figures.
        out["table_gbit_year_available"] = table_av
        out["totals_gbit_year_available"] = totals_av
        out["availability"] = {
            "per_station": av_report,
            "notes": av_notes,
            "beta": req.cloud_aspect_ratio,
            "night_only": req.cloud_night_only,
            "estimator": "expectation",
            "note": "P_CFLOS(eps) = (1-N)^sqrt(1+beta^2 cot^2 eps) [Kauth & "
                    "Penquite 1967], day-weighted over the 12 monthly ERA5 "
                    "cloud-cover distributions and applied inside the time "
                    "integral. Clear-sky totals are reported unchanged "
                    "alongside; the cloud-weighted figure is an UPPER bound on "
                    "the cloud-averaged key (see physics/availability.py).",
        }
        out["meta"]["availability_enabled"] = True

    return out


# ── small utilities ───────────────────────────────────────────────────────

def _linspace(a: float, b: float, n: int) -> List[float]:
    if n < 2:
        return [a]
    step = (b - a) / (n - 1)
    return [round(a + step * i, 6) for i in range(n)]


def _orbit_period_s() -> float:
    from ..physics.constants import MU_EARTH
    a = EARTH_RADIUS_KM + PAPER["altitude_km"]
    return 2.0 * math.pi * math.sqrt(a ** 3 / MU_EARTH)


def _parse_epoch(epoch: str) -> datetime:
    try:
        dt = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(2024, 3, 20, tzinfo=timezone.utc)


def _get_station(sid: str) -> Dict[str, Any]:
    for s in STATIONS:
        if s["id"] == sid:
            return s
    return STATIONS[0]
