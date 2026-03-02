# ---------------------------------------------------------------------------
# app/routers/solver.py
# ---------------------------------------------------------------------------
# Purpose : Unified POST /api/solve endpoint that orchestrates a full
#           QKD satellite-link simulation:  orbit propagation ▸ link geometry
#           ▸ atmospheric channel ▸ QKD key-rate estimation.
#
# This is the core value of moving physics to the backend: the frontend
# sends a compact JSON payload (SolveRequest) and gets back the complete
# result instead of computing anything itself.
#
# Endpoints:
#   POST /api/solve  – run simulation pipeline and return results
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import SolveRequest
from ..physics.geometry import compute_station_metrics, geometric_loss, los_elevation
from ..physics.propagation import propagate_orbit
from ..physics.qkd import calculate_qkd

router = APIRouter(prefix="/api", tags=["Solver"])


def _build_cn2_layers(req: SolveRequest) -> Optional[List[Tuple[float, float]]]:
    """Build Cn² layer list for scintillation if atmosphere model is set.

    Returns list of (altitude_m, Cn²) tuples or None.
    """
    if not req.scintillation_enabled or not req.atmosphere_model:
        return None
    try:
        from ..services.atmosphere_svc import AtmosphereService, AtmosphereQuery
        from datetime import datetime

        query = AtmosphereQuery(
            lat=req.station_lat or 0.0,
            lon=req.station_lon or 0.0,
            timestamp=datetime.fromisoformat(req.epoch) if req.epoch else datetime.utcnow(),
            model=req.atmosphere_model,
            ground_cn2_day=req.ground_cn2_day,
            ground_cn2_night=req.ground_cn2_night,
            wavelength_nm=req.wavelength_nm,
        )
        svc = AtmosphereService()
        profile = svc.build_profile(query)
        if profile and profile.layers:
            return [
                (layer.alt_km * 1000.0, layer.cn2)
                for layer in profile.layers
                if layer.cn2 is not None
            ]
    except Exception:
        pass  # fall back to no scintillation
    return None


def _run_solve(req: SolveRequest) -> Dict[str, Any]:
    """Execute the full simulation pipeline (CPU-bound, runs in threadpool)."""

    # 1. Propagate orbit ───────────────────────────────────────────────
    prop = propagate_orbit(
        a=req.semi_major_axis,
        e=req.eccentricity,
        inc_deg=req.inclination_deg,
        raan_deg=req.raan_deg,
        arg_pe_deg=req.arg_perigee_deg,
        M0_deg=req.mean_anomaly_deg,
        j2_enabled=req.j2_enabled,
        epoch_iso=req.epoch,
        samples_per_orbit=req.samples_per_orbit,
        total_orbits=req.total_orbits,
    )

    result: Dict[str, Any] = {
        "orbit": {
            "semi_major_axis": prop["semi_major"],
            "period_s": prop["orbit_period"],
            "total_time_s": prop["total_time"],
            "samples": len(prop["data_points"]),
        },
        "ground_track": prop["ground_track"],
        "timeline": prop["timeline"],
    }

    # 2. Station metrics (if station is given) ─────────────────────────
    has_station = req.station_lat is not None and req.station_lon is not None
    if has_station:
        station = {"lat": req.station_lat, "lon": req.station_lon}
        optics = {
            "satAperture": req.sat_aperture_m,
            "groundAperture": req.ground_aperture_m,
            "wavelength": req.wavelength_nm,
        }

        # Build link-budget configuration from request fields
        link_budget_cfg = {
            "pointing_error_urad": req.pointing_error_urad,
            "atm_zenith_aod_db": req.atm_zenith_aod_db,
            "atm_zenith_abs_db": req.atm_zenith_abs_db,
            "fixed_optics_loss_db": req.fixed_optics_loss_db,
            "scintillation_enabled": req.scintillation_enabled,
            "scintillation_p0": req.scintillation_p0,
            "background_enabled": req.background_enabled,
            "background_Hrad_W_m2_sr_um": req.background_Hrad_W_m2_sr_um,
            "background_fov_mrad": req.background_fov_mrad,
            "background_delta_lambda_nm": req.background_delta_lambda_nm,
        }

        # Cn² layers for scintillation
        cn2_layers = _build_cn2_layers(req)

        metrics = compute_station_metrics(
            prop["data_points"], station, optics, None,
            link_budget_cfg=link_budget_cfg,
            cn2_layers=cn2_layers,
        )
        result["station_metrics"] = metrics

        # 3. QKD (if protocol requested and station present) ───────────
        if req.qkd_protocol:
            qkd_per_sample = []
            for i, pt in enumerate(prop["data_points"]):
                elev = metrics["elevationDeg"][i]
                if elev <= 0:
                    continue
                loss_db = metrics["lossDb"][i]

                # Effective dark count rate: base + background
                dark_eff = req.dark_count_rate
                if req.background_enabled:
                    dark_eff += metrics["backgroundCps"][i]

                qkd_params = {
                    "photonRate": req.photon_rate,
                    "channelLossdB": loss_db,
                    "detectorEfficiency": req.detector_efficiency,
                    "darkCountRate": dark_eff,
                    "distance": metrics["distanceKm"][i],
                    "elevationDeg": elev,
                }
                qkd_out = calculate_qkd(req.qkd_protocol, qkd_params)
                qkd_out["t"] = prop["timeline"][i]
                qkd_per_sample.append(qkd_out)
            result["qkd"] = qkd_per_sample

    return result


@router.post("/solve")
async def solve(req: SolveRequest):
    """Run a full satellite-link simulation.

    The response contains: orbit parameters, ground track, optional
    station link metrics, and optional QKD key-rate time-series.
    """
    try:
        return await run_in_threadpool(_run_solve, req)
    except Exception as exc:
        raise HTTPException(500, f"Solver error: {exc}") from exc
