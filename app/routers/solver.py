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

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import SolveRequest
from ..physics.geometry import compute_station_metrics, geometric_loss, los_elevation
from ..physics.propagation import propagate_orbit
from ..physics.qkd import calculate_qkd

router = APIRouter(prefix="/api", tags=["Solver"])


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
        metrics = compute_station_metrics(
            prop["data_points"], station, optics, None
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
                coupling = 10 ** (-loss_db / 10.0)
                qkd_params = {
                    "photonRate": req.photon_rate,
                    "coupling": coupling,
                    "detectorEfficiency": req.detector_efficiency,
                    "darkCountRate": req.dark_count_rate,
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
