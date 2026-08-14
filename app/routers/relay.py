# ---------------------------------------------------------------------------
# app/routers/relay.py
# ---------------------------------------------------------------------------
# Purpose : POST /api/relay — trusted node store-and-forward relay.
#
#           Runs /api/solve for two ground stations sharing the same satellite
#           orbit, matches passes by orbit number, and computes min(V_A, V_B)
#           per matched orbit — the throughput bottleneck in a trusted-node
#           relay model.
#
# References:
#   Liao et al., Phys. Rev. Lett. 120, 030501 (2018) — Micius intercontinental
#   QKD relay via trusted node; https://doi.org/10.1103/PhysRevLett.120.030501
#
# Endpoints:
#   POST /api/relay  – run relay simulation for two ground stations
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import RelayRequest
from ..physics.availability import effective_key_mb
from ..physics.key_volume import compute_key_volume
from ..routers.solver import _run_solve
from ..services.pcflos_svc import compute_pcflos, PCFLOSError

router = APIRouter(prefix="/api", tags=["Relay"])
logger = logging.getLogger(__name__)


# ── Module-level helpers (exposed for unit testing) ──────────────────────────

def match_relay_passes(
    passes_a: list[dict],
    passes_b: list[dict],
    orbit_period_s: float,
) -> tuple[list[dict], float]:
    """Match passes from two stations by orbit index and compute bottleneck volume.

    Orbit index is determined by the pass midpoint:
        orbit_idx = int((pass_start_s + pass_end_s) / 2 / orbit_period_s)

    For each orbit seen in Station A, if Station B also has a pass in the
    same orbit, the relay volume = min(V_A, V_B)  (Liao et al. 2018,
    Micius trusted-node model).

    Args:
        passes_a:       Pass list from compute_key_volume for Station A.
        passes_b:       Pass list from compute_key_volume for Station B.
        orbit_period_s: Orbital period in seconds (used for orbit index).

    Returns:
        Tuple of (relay_passes, total_relay_mb) where relay_passes is a list
        of dicts with keys: orbit_idx, volume_a_mb, volume_b_mb,
        relay_volume_mb, pass_a_start_s, pass_b_start_s.
    """
    def orbit_of(p: dict) -> int:
        mid = (p["pass_start_s"] + p["pass_end_s"]) / 2.0
        return int(mid / orbit_period_s)

    # Build lookup: orbit_idx → pass for station B
    b_by_orbit: dict[int, dict] = {orbit_of(p): p for p in passes_b}

    relay_passes: list[dict] = []
    total_relay_mb = 0.0

    for pa in passes_a:
        idx = orbit_of(pa)
        pb = b_by_orbit.get(idx)
        if pb is None:
            continue
        relay_mb = min(pa["key_volume_mb"], pb["key_volume_mb"])
        relay_passes.append({
            "orbit_idx":       idx,
            "volume_a_mb":     pa["key_volume_mb"],
            "volume_b_mb":     pb["key_volume_mb"],
            "relay_volume_mb": relay_mb,
            "pass_a_start_s":  pa["pass_start_s"],
            "pass_b_start_s":  pb["pass_start_s"],
        })
        total_relay_mb += relay_mb

    return relay_passes, total_relay_mb


def apply_pcflos(
    key_volume_result: dict,
    epoch_iso: str,
    pcflos_data: dict,
) -> dict:
    """Apply PCFLOS factor to produce an effective key volume.

    Looks up the monthly PCFLOS for the epoch month.  Falls back to the
    annual PCFLOS if the epoch month is not available in monthly_pcflos.

    Args:
        key_volume_result: Dict from compute_key_volume (must have
                           'total_key_volume_mb').
        epoch_iso:         ISO-8601 epoch string for the simulation start.
        pcflos_data:       Dict from compute_pcflos (must have
                           'monthly_pcflos' and 'annual_pcflos').

    Returns:
        A copy of key_volume_result extended with 'pcflos_factor' and
        'effective_key_volume_mb'.

    Note this is a whole-run scalar taken from the month of the simulation
    EPOCH, and it carries no elevation dependence.  For a per-pass,
    elevation-resolved factor use ``availability_enabled`` on /api/solve
    (physics/availability.py); this path stays as-is because the relay endpoint
    reports one aggregate figure.
    """
    try:
        epoch_dt = datetime.fromisoformat(epoch_iso.replace("Z", "+00:00"))
        month = epoch_dt.month
    except (ValueError, AttributeError):
        month = None

    monthly = pcflos_data.get("monthly_pcflos", {})
    annual  = pcflos_data.get("annual_pcflos", 1.0)
    pcflos_factor = annual
    if month is not None:
        # A JSON round-trip stringifies integer month keys, and .get(3) would
        # then miss and fall back to the annual figure with no log line — a
        # silent seasonal error.  Accept both key types.
        for key in (month, str(month)):
            if key in monthly:
                pcflos_factor = monthly[key]
                break

    total_mb = key_volume_result.get("total_key_volume_mb", 0.0)
    return {
        **key_volume_result,
        "pcflos_factor":          pcflos_factor,
        # One composition rule for the whole codebase, so the clamping and the
        # "each factor exactly once" discipline live in a single place.
        "effective_key_volume_mb": effective_key_mb(
            total_mb, availability=pcflos_factor),
    }


# ── Router endpoint ───────────────────────────────────────────────────────────

@router.post("/relay")
async def relay(req: RelayRequest):
    """Run a trusted node relay simulation between two ground stations.

    Executes /api/solve for each station sequentially, matches passes by
    orbit index, and computes min(V_A, V_B) relay volume per matched orbit.
    Optionally applies PCFLOS factors (soft failure — relay continues if
    cloud data is unavailable).

    Returns 400 if qkd_protocol is not set on either station solve request
    (key volume requires QKD data).
    """
    # Ensure both solve requests have QKD protocol set (required for key volume)
    epoch_iso_a = req.solve_a.epoch or ""
    epoch_iso_b = req.solve_b.epoch or ""

    try:
        result_a = await run_in_threadpool(_run_solve, req.solve_a)
        result_b = await run_in_threadpool(_run_solve, req.solve_b)
    except Exception as exc:
        logger.exception("Relay solve error")
        raise HTTPException(500, f"Solve error: {exc}") from exc

    kv_a = result_a.get("key_volume")
    kv_b = result_b.get("key_volume")

    if kv_a is None or kv_b is None:
        raise HTTPException(
            400,
            "Both solve_a and solve_b must specify a qkd_protocol to compute key volumes."
        )

    orbit_period_s = result_a["orbit"]["period_s"]
    relay_passes, total_relay_mb = match_relay_passes(
        kv_a["passes"], kv_b["passes"], orbit_period_s
    )

    # --- Optional PCFLOS factors (soft failure) ---
    # Climatology year = epoch year − 1, because ERA5 lags reality by ~5 days so
    # the current year would come back partial (and a partial year silently
    # biases the annual mean toward whichever months exist).  A non-numeric
    # epoch prefix used to raise an uncaught ValueError here, before the try
    # blocks below, surfacing as a bare 500.
    def _clim_year(epoch_iso: str) -> int:
        try:
            return int(epoch_iso[:4]) - 1
        except (TypeError, ValueError):
            return 2024

    pcflos_year_a = _clim_year(epoch_iso_a)
    pcflos_year_b = _clim_year(epoch_iso_b)

    station_a: dict = dict(kv_a)
    station_b: dict = dict(kv_b)
    effective_relay_mb: Optional[float] = None
    relay_pcflos_factor: Optional[float] = None

    lat_a = req.solve_a.station_lat
    lon_a = req.solve_a.station_lon
    lat_b = req.solve_b.station_lat
    lon_b = req.solve_b.station_lon

    def _adopt_per_pass(kv: dict) -> Optional[dict]:
        """Reuse the per-pass factor when /api/solve already computed one.

        ``solve_a``/``solve_b`` are full SolveRequests, so a caller can enable
        ``availability_enabled`` there.  That factor is strictly better than the
        one this endpoint would compute — per pass and elevation-resolved rather
        than one epoch-month scalar — so it wins, and exactly ONE cloud factor
        per station reaches the response instead of two competing ones.
        """
        total_av = kv.get("total_key_volume_available_mb")
        if total_av is None:
            return None
        return {
            **kv,
            "pcflos_factor": kv.get("mean_availability", 1.0),
            "effective_key_volume_mb": total_av,
            "pcflos_note": "per-pass elevation-resolved availability from "
                           "/api/solve (availability_enabled); the epoch-month "
                           "scalar was not applied",
        }

    if lat_a is not None and lon_a is not None:
        adopted = _adopt_per_pass(kv_a)
        if adopted is not None:
            station_a = adopted
        else:
            try:
                pd_a = await run_in_threadpool(
                    compute_pcflos, lat_a, lon_a, pcflos_year_a, req.cloud_threshold_pct
                )
                station_a = apply_pcflos(kv_a, epoch_iso_a, pd_a)
            except PCFLOSError:
                logger.warning("PCFLOS unavailable for station A — skipping cloud factor")

    if lat_b is not None and lon_b is not None:
        adopted = _adopt_per_pass(kv_b)
        if adopted is not None:
            station_b = adopted
        else:
            try:
                pd_b = await run_in_threadpool(
                    compute_pcflos, lat_b, lon_b, pcflos_year_b, req.cloud_threshold_pct
                )
                station_b = apply_pcflos(kv_b, epoch_iso_b, pd_b)
            except PCFLOSError:
                logger.warning("PCFLOS unavailable for station B — skipping cloud factor")

    # Effective relay volume = relay_total × min(pcflos_A, pcflos_B) if both available
    f_a = station_a.get("pcflos_factor")
    f_b = station_b.get("pcflos_factor")
    if f_a is not None and f_b is not None:
        relay_pcflos_factor = min(f_a, f_b)
        effective_relay_mb = total_relay_mb * relay_pcflos_factor

    relay_block: dict = {
        "relay_passes":       relay_passes,
        "total_relay_mb":     total_relay_mb,
        "matched_orbit_count": len(relay_passes),
        "total_pass_count_a": kv_a["pass_count"],
        "total_pass_count_b": kv_b["pass_count"],
        "orbit_period_s":     orbit_period_s,
    }
    if effective_relay_mb is not None:
        relay_block["effective_relay_mb"]  = effective_relay_mb
        relay_block["relay_pcflos_factor"] = relay_pcflos_factor

    return {
        "station_a": station_a,
        "station_b": station_b,
        "relay":     relay_block,
    }
