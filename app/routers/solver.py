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
#   POST /api/solve           – run simulation for one station
#   POST /api/solve/multi-ogs – run same satellite over multiple stations
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import MultiOGSSolveRequest, SolveRequest
from ..physics.geometry import compute_station_metrics, geometric_loss, los_elevation
from ..physics.key_volume import compute_key_volume
from ..physics.link_budget import gated_background_cps
from ..physics.propagation import propagate_orbit
from ..physics.qkd import calculate_qkd

router = APIRouter(prefix="/api", tags=["Solver"])
logger = logging.getLogger(__name__)

# OGS store injected from backend.py so the multi-OGS endpoint can look up
# stations by ID without duplicating the store path logic.
_store = None  # type: ignore


def set_store(store) -> None:  # noqa: ANN001
    global _store
    _store = store


def resolve_stations(
    station_ids: Optional[Sequence[str]],
    inline_stations: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Resolve station IDs against the OGS store and merge inline definitions.

    Shared by the multi-OGS solver and the constellation study so a station id
    means the same record — including its aperture and altitude — in both.

    Raises:
        HTTPException: 500 if the store is missing, 404 for an unknown id, 400
            if the merged list is empty.
    """
    stations: List[Dict[str, Any]] = []

    if station_ids:
        if _store is None:
            raise HTTPException(500, "OGS store not initialised")
        by_id = {r["id"]: r for r in _store.list() if r.get("id")}
        for sid in station_ids:
            rec = by_id.get(sid)
            if rec is None:
                raise HTTPException(404, f"Station '{sid}' not found in OGS store")
            stations.append(rec)

    if inline_stations:
        for s in inline_stations:
            stations.append(s.dict() if hasattr(s, "dict") else dict(s))

    if not stations:
        raise HTTPException(
            400,
            "Provide at least one station via 'station_ids' or 'inline_stations'",
        )
    return stations


def _build_cn2_layers(
    req: SolveRequest,
    station_rec: Optional[Dict[str, Any]] = None,
) -> Optional[List[Tuple[float, float]]]:
    """Build Cn² layer list for scintillation if atmosphere model is set.

    Args:
        req:         SolveRequest carrying the model choice and ground Cn².
        station_rec: The station this profile is for.  Its altitude and
                     coordinates OVERRIDE the request's, because a run over
                     several stations carries only one ``station_altitude_m``
                     and one ``station_lat/lon``.  Without this the turbulence
                     profile of every station in a multi-station run came from
                     whichever scalar the request happened to hold — Teide at
                     2390 m got a sea-level boundary layer, which is precisely
                     the term the modified-HV model exists to resolve
                     (Ntanos 2021, Eq. 11), while the geometry used the real
                     altitude. Altitude is the main reason to site an OGS high.

    Returns list of (altitude_m, Cn²) tuples or None.
    """
    if not req.scintillation_enabled or not req.atmosphere_model:
        return None

    rec = station_rec or {}
    h_gs_m = float(rec.get("altitude_m", req.station_altitude_m))
    lat = rec.get("lat", req.station_lat)
    lon = rec.get("lon", req.station_lon)

    # Modified Hufnagel-Valley (Ntanos 2021, Eq. 11) is network-free and folds
    # the OGS altitude into the boundary-layer term.  Build it directly from the
    # pure model rather than via the weather-fetching AtmosphereService.
    model_name = (req.atmosphere_model or "").strip().lower()
    if model_name in ("modified-hv", "modified-hufnagel-valley"):
        try:
            from ..physics.atmosphere_models import modified_hv_layers
            ground_cn2 = req.ground_cn2_night  # paper is nighttime; A0 = 1.7e-14
            return modified_hv_layers(
                h_gs_m=h_gs_m,
                ground_cn2=ground_cn2,
                u_rms=req.wind_rms_ms,
            )
        except Exception:
            logger.warning("Failed to build modified-HV Cn2 layers", exc_info=True)
            return None

    try:
        from ..services.atmosphere_svc import AtmosphereService, AtmosphereQuery
        from datetime import datetime

        query = AtmosphereQuery(
            lat=lat or 0.0,
            lon=lon or 0.0,
            timestamp=datetime.fromisoformat(req.epoch) if req.epoch else datetime.utcnow(),
            model=req.atmosphere_model,
            ground_cn2_day=req.ground_cn2_day,
            ground_cn2_night=req.ground_cn2_night,
            wavelength_nm=req.wavelength_nm,
        )
        svc = AtmosphereService()
        profile = svc.build_profile(query)  # returns a dict (AtmosphericProfile.to_dict)
        layers = (profile or {}).get("layers") or []
        if layers:
            return [
                (layer["alt_km"] * 1000.0, layer["cn2"])
                for layer in layers
                if layer.get("cn2") is not None
            ]
    except Exception:
        logger.warning("Failed to build Cn2 layers for scintillation — falling back to no scintillation", exc_info=True)
    return None


def _build_link_budget_cfg(req: SolveRequest) -> Dict[str, Any]:
    """Extract link-budget config dict from a SolveRequest."""
    return {
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
        "sun_exclusion_deg": req.sun_exclusion_deg,
        "tx_power_dbm": req.tx_power_dbm,
        "rx_sensitivity_dbm": req.rx_sensitivity_dbm,
        "pat_fading_enabled": req.pat_fading_enabled,
        "dynamic_background_enabled": req.dynamic_background_enabled,
        "min_elevation_deg": req.min_elevation_deg,
        "geometric_model": req.geometric_model,
        "pointing_model": req.pointing_model,
    }


def _make_finite_key_evaluator(
    *,
    timeline: List[float],
    gains: Tuple[List[float], List[float], List[float]],
    errors: Tuple[List[float], List[float]],
    mu_used: Dict[str, float],
    req: SolveRequest,
):
    """Build ``evaluate(ranges) -> dict | None`` for the Lim et al. 2014 bound.

    *ranges* is a sequence of INCLUSIVE sample-index ranges forming one
    finite-key block.  A whole pass is a single range; a pass that a network
    scheduler served only in part (see ``physics/scheduling.py``) is several,
    and the counts are accumulated over exactly the served intervals.  That is
    the honest treatment: the block is what the receiver actually recorded, and
    the Hoeffding deviations grow as sqrt of it, so a fragmented pass must be
    re-evaluated rather than pro-rated.

    Returns None when the intensity configuration makes the bound impossible.
    """
    import numpy as np

    from ..physics.finite_key import lim2014_finite_fraction

    d1_s, d2_s, y0_s = gains
    e1_s, e2_s = errors
    t_arr = np.asarray(timeline, dtype=float)

    mu_1 = float(mu_used.get("mu_signal", 0.6))
    mu_2 = float(mu_used.get("mu_decoy", 0.1))
    intensities = (mu_1, mu_2, 0.0)

    q_x = float(req.basis_bias_qx)
    p_1 = float(req.p_signal)
    p_2 = float(req.p_decoy)
    p_3 = 1.0 - p_1 - p_2
    probs = (p_1, p_2, p_3)
    f_rep = float(req.photon_rate)
    f_ec = float(req.ec_efficiency) if req.ec_efficiency is not None else 1.16

    d_arr = (np.asarray(d1_s, dtype=float), np.asarray(d2_s, dtype=float),
             np.asarray(y0_s, dtype=float))
    # E_3 = e_0 = 1/2 for the vacuum intensity: every vacuum click is random.
    e_arr = (np.asarray(e1_s, dtype=float), np.asarray(e2_s, dtype=float),
             np.full(len(d1_s), 0.5))

    if p_3 <= 0.0:
        logger.warning(
            "p_signal + p_decoy = %.4f >= 1 — no vacuum probability left, so the "
            "Lim 2014 vacuum decoy cannot be estimated; finite key skipped.",
            p_1 + p_2,
        )
        return None

    kw = dict(intensities=intensities, probs=probs,
              eps_sec=float(req.epsilon_sec),
              eps_cor=float(req.epsilon_cor), f_ec=f_ec)

    def _counts(ranges: Sequence[Tuple[int, int]]):
        """Accumulate Lim 2014 block counts over a set of inclusive ranges."""
        n_x_k, n_z_k, m_z_k = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        m_x = 0.0
        for start, end in ranges:
            t_slice = t_arr[start : end + 1]
            if t_slice.size < 2:
                continue
            for k in range(3):
                dk = d_arr[k][start : end + 1]
                ek = e_arr[k][start : end + 1]
                int_d = float(np.trapezoid(dk, t_slice))
                int_de = float(np.trapezoid(dk * ek, t_slice))
                n_x_k[k] += q_x ** 2 * probs[k] * f_rep * int_d
                n_z_k[k] += (1.0 - q_x) ** 2 * probs[k] * f_rep * int_d
                m_z_k[k] += (1.0 - q_x) ** 2 * probs[k] * f_rep * int_de
                m_x += q_x ** 2 * probs[k] * f_rep * int_de
        return n_x_k, n_z_k, m_z_k, m_x

    def evaluate(ranges: Sequence[Tuple[int, int]]) -> Optional[Dict[str, Any]]:
        n_x_k, n_z_k, m_z_k, m_x = _counts(ranges)
        if sum(n_x_k) <= 0.0:
            return {"nSifted": 0.0, "fkFraction": 0.0, "ellFiniteBits": 0.0,
                    "ellAsymptoticBits": 0.0, "phaseErrorX": 0.0}
        res = lim2014_finite_fraction(
            tuple(n_x_k), tuple(n_z_k), tuple(m_z_k), m_x, **kw)
        return {
            "nSifted": res["n_x"],
            "fkFraction": res["fraction"],
            "ellFiniteBits": res["ell_finite"],
            "ellAsymptoticBits": res["ell_asymptotic"],
            "phaseErrorX": res["phi_x"],
        }

    evaluate.counts = _counts          # type: ignore[attr-defined]
    evaluate.kwargs = kw               # type: ignore[attr-defined]
    return evaluate


def _make_finite_key_hook(
    *,
    timeline: List[float],
    gains: Tuple[List[float], List[float], List[float]],
    errors: Tuple[List[float], List[float]],
    mu_used: Dict[str, float],
    req: SolveRequest,
):
    """Build a per-pass hook that evaluates the Lim et al. 2014 finite-key bound.

    One satellite pass = one finite-key block, which is the published
    convention (Islam et al., PRX Quantum 5, 030101 (2024) §III B: "the key is
    extracted from data for the whole pass as a single block without
    partitioning").

    The returned callable takes the inclusive sample-index range of a pass and
    accumulates the block statistics that Lim et al. 2014 Eqs. (2)-(5) need:

        n_{X,k} = q_x^2     p_k f_rep ∫ D_k(t) dt
        n_{Z,k} = (1-q_x)^2 p_k f_rep ∫ D_k(t) dt
        m_{Z,k} = (1-q_x)^2 p_k f_rep ∫ D_k(t) E_k(t) dt
        m_X     = q_x^2 f_rep Σ_k p_k ∫ D_k(t) E_k(t) dt

    Note that E_k is weighted *inside* the time integral.  Multiplying a
    pass-total detection count by a pass-mean error rate is not the same
    quantity and biases the phase-error bound, because E_k rises steeply at low
    elevation exactly where D_k falls.

    Intensities are (mu_signal, mu_decoy, 0): the third is a true vacuum decoy,
    for which D_3 = Y_0 and E_3 = e_0 = 1/2 exactly.

    The block arithmetic itself lives in :func:`_make_finite_key_evaluator` so
    the network scheduler can re-evaluate the same bound over a partially served
    pass without duplicating it.
    """
    from ..physics.finite_key import lim2014_finite_fraction

    evaluate = _make_finite_key_evaluator(
        timeline=timeline, gains=gains, errors=errors,
        mu_used=mu_used, req=req)
    if evaluate is None:
        return None
    counts = evaluate.counts          # type: ignore[attr-defined]
    kw = evaluate.kwargs              # type: ignore[attr-defined]

    def _hook(start: int, end: int) -> Optional[Dict[str, Any]]:
        if end - start < 1:
            return None
        out = evaluate([(start, end)])
        if out is None or out.get("nSifted", 0.0) <= 0.0:
            return {"nSifted": 0.0, "fkFraction": 0.0, "ellFiniteBits": 0.0}
        n_x_k, n_z_k, m_z_k, m_x = counts([(start, end)])
        ell_full = out["ellFiniteBits"]

        if req.fk_block_fractions:
            # ell(f*n), NOT f*ell(n).  Every count scales linearly with the
            # usable fraction of the pass, while the Hoeffding deviations scale
            # as sqrt(f*n) — which is exactly why the shortfall is nonlinear and
            # why the key vanishes entirely below the threshold block size.  The
            # gap between these two numbers IS the cost of a shortened pass.
            scaled: Dict[str, Any] = {}
            for f in req.fk_block_fractions:
                f = max(0.0, min(1.0, float(f)))
                sub = lim2014_finite_fraction(
                    tuple(v * f for v in n_x_k), tuple(v * f for v in n_z_k),
                    tuple(v * f for v in m_z_k), m_x * f, **kw)
                scaled[f"{f:g}"] = {
                    "nSifted": sub["n_x"],
                    "ellFiniteBits": sub["ell_finite"],
                    # < 1 means ell(f*n) < f*ell(n), i.e. shortening the block
                    # costs more than pro rata.  0 means the key is gone.
                    "shortfall": (
                        sub["ell_finite"] / (f * ell_full)
                        if f > 0.0 and ell_full > 0.0 else 0.0
                    ),
                }
            out["ellBlockFractions"] = scaled

        return out

    return _hook


def _make_availability_profile(
    station_rec: Dict[str, Any],
    req,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Build the per-station PCFLOS(elevation) profile for a solve.

    Returns ``(profile, note)``.  The profile is a single elevation table shared
    by every pass of this station — evaluated for the month the pass falls in
    would need one table per month, which :func:`compute_key_volume` supports by
    passing a callable; here we hand it a month-resolving closure so a run
    spanning a month boundary uses each pass's own climatology.

    ``note`` is non-None whenever availability was requested but could not be
    produced.  Missing cloud data must never silently become "clear skies": the
    factor stays 1.0 and the response says why.
    """
    from ..physics.availability import monthly_cover_stats, pcflos_profile

    hourly = req.cloud_cover_hourly
    if not hourly:
        # No injected series: fall back to the archive.  Deliberately a
        # fetch-on-demand, so a study run that supplies its own cached table
        # never touches the network.
        year = req.cloud_year
        if year is None:
            try:
                year = int((req.epoch or "")[:4]) - 1
            except (TypeError, ValueError):
                year = 2024
        try:
            from ..services.pcflos_svc import PCFLOSError, fetch_hourly_cover
            hourly = fetch_hourly_cover(
                station_rec["lat"], station_rec["lon"], year)
        except Exception as exc:      # PCFLOSError, or anything the fetch raises
            return None, (
                "availability_enabled ignored: no cloud-cover data "
                f"(year {year}) — {type(exc).__name__}: {exc}. Supply "
                "cloud_cover_hourly to run offline."
            )

    if req.availability_estimator not in ("expectation", "threshold"):
        return None, (
            "availability_enabled ignored: unknown availability_estimator "
            f"{req.availability_estimator!r} (expected 'expectation' or "
            "'threshold')."
        )

    stats = monthly_cover_stats(
        hourly,
        night_only=bool(req.cloud_night_only),
        lon_deg=float(station_rec["lon"]),
    )
    if not stats.get("valid_hours"):
        return None, (
            "availability_enabled ignored: the cloud-cover series contains no "
            "valid hours" + (" after night filtering" if req.cloud_night_only
                             else "") + "."
        )

    beta = float(req.cloud_aspect_ratio)
    if req.availability_estimator == "threshold":
        # The threshold estimator has no elevation model, so it is offered only
        # as the flat zenith-like comparison it actually is — never dressed up
        # with a shape factor it cannot support.
        from ..physics.availability import threshold_pcflos
        table = threshold_pcflos(
            hourly, float(req.cloud_threshold_pct),
            night_only=bool(req.cloud_night_only),
            lon_deg=float(station_rec["lon"]),
        )
        n_grid = int(round(90.0 / 0.5)) + 1

        def _profile(month: Optional[int]) -> Dict[str, Any]:
            monthly = table["monthly"]
            p = monthly.get(month, table["annual"]) if month is not None \
                else table["annual"]
            return {"p": [p] * n_grid, "step_deg": 0.5, "beta": 0.0,
                    "month": month, "zenith": p, "resolved": True}

        return _profile, None

    cache: Dict[Optional[int], Dict[str, Any]] = {}

    def _profile(month: Optional[int]) -> Dict[str, Any]:
        prof = cache.get(month)
        if prof is None:
            prof = pcflos_profile(stats, month=month, beta=beta)
            cache[month] = prof
        return prof

    return _profile, None


def _run_single_station(
    prop: Dict[str, Any],
    station_rec: Dict[str, Any],
    req: SolveRequest,
    *,
    collect_fk_evaluator: bool = False,
) -> Dict[str, Any]:
    """Run steps 2–4 (metrics + QKD + key volume) for one ground station.

    Args:
        prop:        Propagated orbit dict from :func:`propagate_orbit`.
        station_rec: Station record with keys ``lat``, ``lon``,
                     ``altitude_m`` (opt.), ``aperture_m`` (opt.).
        req:         SolveRequest carrying optics, QKD, and physics settings.
                     The ``station_lat/lon`` fields are ignored; values from
                     *station_rec* take precedence.

        collect_fk_evaluator: when True, the result carries a non-JSON key
                     ``_fk_evaluate`` — the Lim 2014 block evaluator bound to
                     THIS pair's channel statistics.  The constellation study
                     needs it to re-derive the finite key over the fragments a
                     scheduler actually served, which is not recoverable from
                     the per-pass numbers: a block half as long keeps less than
                     half the key.  Callers must strip the key before
                     serialising.

    Returns:
        Dict with ``station_metrics`` and optionally ``qkd``,
        ``key_volume``, and ``qkd_summary``.
    """
    station = {
        "lat": station_rec["lat"],
        "lon": station_rec["lon"],
        "altitude_m": station_rec.get("altitude_m", 0.0),
    }
    # Station aperture overrides the request's ground_aperture_m when present
    ground_aperture = station_rec.get("aperture_m", req.ground_aperture_m)
    optics = {
        "satAperture": req.sat_aperture_m,
        "groundAperture": ground_aperture,
        "wavelength": req.wavelength_nm,
    }

    link_budget_cfg = _build_link_budget_cfg(req)
    cn2_layers = _build_cn2_layers(req, station_rec)

    metrics = compute_station_metrics(
        prop["data_points"], station, optics, None,
        link_budget_cfg=link_budget_cfg,
        cn2_layers=cn2_layers,
        link_direction=req.link_direction,
        epoch_iso=req.epoch,
    )
    station_result: Dict[str, Any] = {"station_metrics": metrics}

    if not req.qkd_protocol:
        return station_result

    # ── QKD per-sample ─────────────────────────────────────────────────
    n_pts = len(prop["data_points"])
    qkd_per_sample: List[Dict[str, Any]] = []
    skr_kbps_series: List[Optional[float]] = [None] * n_pts
    skr_pp_series: List[Optional[float]] = [None] * n_pts
    qber_pct_series: List[Optional[float]] = [None] * n_pts

    # Per-intensity channel statistics for the per-pass finite-key block
    # (Lim et al. 2014).  Dense arrays of gains D_k(t) and error rates E_k(t),
    # zero wherever no link existed — matching the key-volume integral, which
    # also zeroes those samples.
    is_decoy = (req.qkd_protocol or "").strip().lower() in (
        "bb84-decoy", "bb84decoy",
    )
    collect_decoy = bool(req.finite_key_enabled and is_decoy)
    d1_s = [0.0] * n_pts     # D_1, signal gain Q_s
    d2_s = [0.0] * n_pts     # D_2, decoy gain Q_d
    y0_s = [0.0] * n_pts     # D_3 = Y_0 (vacuum intensity mu_3 = 0)
    e1_s = [0.0] * n_pts     # E_1 (fraction)
    e2_s = [0.0] * n_pts     # E_2 (fraction)
    mu_used: Dict[str, float] = {}

    # Paper-mode QKD extras, forwarded only when set (backward-compatible).
    qkd_extra: Dict[str, Any] = {}
    if req.mu_signal is not None:
        qkd_extra["mu_signal"] = req.mu_signal
    if req.mu_decoy is not None:
        qkd_extra["mu_decoy"] = req.mu_decoy
    if req.decoy_q is not None:
        qkd_extra["q"] = req.decoy_q
    if req.e_optical is not None:
        qkd_extra["e_optical"] = req.e_optical
    if req.ec_efficiency is not None:
        qkd_extra["f_ec"] = req.ec_efficiency
    if req.paper_noise:
        qkd_extra["paper_noise"] = True
        qkd_extra["gate_time_s"] = req.gate_time_s

    # ── Monte Carlo channel realizations (optional) ────────────────────
    # Drawn per accepted sample; see the field docs in models.SolveRequest for
    # the i.i.d. caveat that must accompany any published band.
    mc_on = bool(req.monte_carlo_enabled)
    mc_p_series: Dict[str, List[Optional[float]]] = {}
    mc_outage_series: List[Optional[float]] = [None] * n_pts
    if mc_on:
        from ..physics.monte_carlo import monte_carlo_key_rate
        for q in req.mc_quantiles:
            mc_p_series[f"p{int(round(q))}"] = [None] * n_pts

    for i in range(n_pts):
        elev = metrics["elevationDeg"][i]
        if elev is None or elev <= 0:
            continue
        if not metrics["linkEstablished"][i]:
            continue
        if metrics["sunExcluded"][i]:
            continue
        loss_db = metrics["lossDb"][i]
        bg_cps = metrics["backgroundCps"][i] if req.background_enabled else 0.0
        # Temporal gating (daytime QKD): a narrow detection gate of width
        # gate_time_s admits background only over a duty cycle Δt_gate·f_rep.
        if req.temporal_gating_enabled and req.gate_time_s > 0.0:
            bg_cps = gated_background_cps(bg_cps, req.gate_time_s, req.photon_rate)

        qkd_params = {
            "photonRate": req.photon_rate,
            "channelLossdB": loss_db,
            "detectorEfficiency": req.detector_efficiency,
            "darkCountRate": req.dark_count_rate,
            "backgroundCps": bg_cps,
            "distance": metrics["distanceKm"][i],
            "elevationDeg": elev,
            **qkd_extra,
        }
        qkd_out = calculate_qkd(req.qkd_protocol, qkd_params)
        qkd_out["t"] = prop["timeline"][i]
        qkd_per_sample.append(qkd_out)
        skr_kbps_series[i] = qkd_out.get("secureKeyRate", 0.0)
        skr_pp_series[i] = qkd_out.get("secureKeyRatePerPulse", None)
        qber_pct_series[i] = qkd_out.get("qber", None)

        if collect_decoy:
            d1_s[i] = float(qkd_out.get("signalGain", 0.0) or 0.0)
            d2_s[i] = float(qkd_out.get("decoyGain", 0.0) or 0.0)
            y0_s[i] = float(qkd_out.get("vacuumYield", 0.0) or 0.0)
            e1_s[i] = float(qkd_out.get("signalQber", 0.0) or 0.0)
            e2_s[i] = float(qkd_out.get("decoyQber", 0.0) or 0.0)
            # Read the intensities back from the calculator rather than from the
            # request, so the block is built with the values actually used.
            if not mu_used:
                mu_used = {
                    "mu_signal": float(qkd_out.get("mu_signal", 0.6)),
                    "mu_decoy": float(qkd_out.get("mu_decoy", 0.1)),
                }

        if mc_on:
            # DE-BIAS THE BASE LOSS.  metrics["lossDb"] already contains the
            # p0-quantile scintillation margin and the Rayleigh-AVERAGED
            # pointing fade.  Sampling fading on top of a loss that already
            # embeds it would count both twice — the band would sit far below
            # the deterministic curve and the outage would be pure artefact.
            # So strip exactly the two deterministic fade terms and let the
            # sampler put back its own realizations.
            base_loss = (
                loss_db
                - float(metrics["scintLossDb"][i] or 0.0)
                - float(metrics["pointingLossDb"][i] or 0.0)
            )
            mc_params = dict(qkd_params)
            mc_params["channelLossdB"] = base_loss
            mc = monte_carlo_key_rate(
                mc_params,
                protocol=req.qkd_protocol,
                sigma_r2=float(metrics["sigmaR2"][i] or 0.0),
                aperture_avg=float(metrics["apertureAvg"][i] or 1.0),
                jitter_rad=float(metrics["pointingJitterUrad"][i] or 0.0) * 1e-6,
                divergence_rad=float(metrics["divergenceRad"][i] or 0.0),
                n_realizations=int(req.mc_realizations),
                quantiles=tuple(req.mc_quantiles),
                # Per-sample offset from a fixed base: independent draws across
                # the pass, identical across reruns of the same configuration.
                seed=(None if req.mc_seed is None else int(req.mc_seed) + i),
            )
            for q in req.mc_quantiles:
                key = f"p{int(round(q))}"
                mc_p_series[key][i] = mc["skr_kbps"][key]
            mc_outage_series[i] = mc["outage_probability"]

    metrics["skrKbps"] = skr_kbps_series
    metrics["skrPerPulse"] = skr_pp_series
    metrics["qberPct"] = qber_pct_series
    station_result["qkd"] = qkd_per_sample

    if mc_on:
        for key, series in mc_p_series.items():
            metrics[f"skrKbps{key.upper()}"] = series
        metrics["outageProbability"] = mc_outage_series
        # Link-time-weighted outage: the fraction of CONTACT time the link
        # spends unable to distil, not the fraction of samples — low-elevation
        # samples are the ones that fail and they are not equally spaced in the
        # sense that matters, so an unweighted mean over samples would depend
        # on the sampling grid.
        t_line = prop["timeline"]
        num = 0.0
        den = 0.0
        for i in range(n_pts - 1):
            a, b = mc_outage_series[i], mc_outage_series[i + 1]
            if a is None or b is None:
                continue
            dt = float(t_line[i + 1]) - float(t_line[i])
            num += 0.5 * (a + b) * dt
            den += dt
        station_result["monte_carlo"] = {
            "enabled": True,
            "realizations": int(req.mc_realizations),
            "seed": req.mc_seed,
            "quantiles": list(req.mc_quantiles),
            "link_time_outage": (num / den) if den > 0 else None,
            "note": (
                "i.i.d. draws per sample: this is the INSTANTANEOUS key-rate "
                "distribution. Scintillation is temporally correlated on "
                "~1/f_Greenwood, so the outage is a fraction of independent "
                "instants, not of pass time, and says nothing about fade "
                "duration. The deterministic curve uses the p0 scintillation "
                "quantile as a margin, so the MC median sits ABOVE it by "
                "construction."
            ),
        }

    # ── Per-pass finite-key block (Lim et al. 2014, PRA 89, 022307) ─────
    pass_hook = None
    if collect_decoy:
        pass_hook = _make_finite_key_hook(
            timeline=prop["timeline"],
            gains=(d1_s, d2_s, y0_s),
            errors=(e1_s, e2_s),
            mu_used=mu_used,
            req=req,
        )
        if collect_fk_evaluator:
            station_result["_fk_evaluate"] = _make_finite_key_evaluator(
                timeline=prop["timeline"],
                gains=(d1_s, d2_s, y0_s),
                errors=(e1_s, e2_s),
                mu_used=mu_used,
                req=req,
            )

    # ── Cloud availability ─────────────────────────────────────────────
    availability_profile = None
    availability_note = None
    if req.availability_enabled:
        availability_profile, availability_note = _make_availability_profile(
            station_rec, req)

    # ── Key volume ─────────────────────────────────────────────────────
    key_vol = compute_key_volume(
        timeline=prop["timeline"],
        link_established=metrics["linkEstablished"],
        elevation_deg=metrics["elevationDeg"],
        qkd_per_sample=qkd_per_sample,
        epoch_iso=req.epoch or "",
        elevation_threshold_deg=req.elevation_threshold_deg,
        pass_hook=pass_hook,
        availability_profile=availability_profile,
        availability_beta=float(req.cloud_aspect_ratio),
    )
    if availability_note:
        key_vol["availability_note"] = availability_note
        logger.warning("availability skipped: %s", availability_note)
    elif availability_profile is not None:
        key_vol["availability_meta"] = {
            "estimator": req.availability_estimator,
            "beta": float(req.cloud_aspect_ratio),
            "night_only": bool(req.cloud_night_only),
            "threshold_pct": float(req.cloud_threshold_pct),
            "source": "injected" if req.cloud_cover_hourly else "archive",
        }
    if req.finite_key_enabled and not is_decoy:
        # Never degrade silently: the bound is a decoy-state bound, so asking
        # for it on another protocol must say so rather than return nothing.
        key_vol["finite_key_note"] = (
            "finite_key_enabled ignored: the Lim et al. 2014 bound applies to "
            f"decoy-state BB84; protocol was '{req.qkd_protocol}'."
        )
        logger.warning(
            "finite_key_enabled with protocol %r — skipped (decoy-state only)",
            req.qkd_protocol,
        )
    station_result["key_volume"] = key_vol

    # ── Summary scalars for comparison table ───────────────────────────
    valid_skr = [s for s in skr_kbps_series if s is not None and s > 0]
    valid_elev = [e for e in metrics["elevationDeg"] if e is not None]
    valid_qber = [q for q in qber_pct_series if q is not None]
    station_result["qkd_summary"] = {
        "pass_count": key_vol["pass_count"],
        "total_key_volume_mb": key_vol["total_key_volume_mb"],
        "peak_skr_kbps": max(valid_skr) if valid_skr else 0.0,
        "mean_skr_kbps": sum(valid_skr) / len(valid_skr) if valid_skr else 0.0,
        "max_elevation_deg": max(valid_elev) if valid_elev else 0.0,
        "mean_qber_pct": sum(valid_qber) / len(valid_qber) if valid_qber else None,
        "link_samples": len(qkd_per_sample),
        "ground_aperture_m": ground_aperture,
    }

    return station_result


def _run_solve(req: SolveRequest) -> Dict[str, Any]:
    """Execute the full simulation pipeline (CPU-bound, runs in threadpool)."""
    logger.info(
        "Solve request: a=%.1f km, e=%.4f, inc=%.1f deg",
        req.semi_major_axis, req.eccentricity, req.inclination_deg,
    )

    # 1. Propagate orbit ───────────────────────────────────────────────
    prop = propagate_orbit(
        a=req.semi_major_axis,
        e=req.eccentricity,
        inc_deg=req.inclination_deg,
        raan_deg=req.raan_deg,
        arg_pe_deg=req.arg_perigee_deg,
        M0_deg=req.mean_anomaly_deg,
        j2_enabled=req.j2_enabled,
        j3_enabled=req.j3_enabled,
        j4_enabled=req.j4_enabled,
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

    # 2–4. Station metrics + QKD + key volume (if station given) ───────
    has_station = req.station_lat is not None and req.station_lon is not None
    if has_station:
        station_rec = {
            "lat": req.station_lat,
            "lon": req.station_lon,
            "altitude_m": req.station_altitude_m,
            "aperture_m": req.ground_aperture_m,
        }
        station_out = _run_single_station(prop, station_rec, req)
        result["station_metrics"] = station_out["station_metrics"]
        if "qkd" in station_out:
            result["qkd"] = station_out["qkd"]
        if "key_volume" in station_out:
            result["key_volume"] = station_out["key_volume"]
        if "monte_carlo" in station_out:
            result["monte_carlo"] = station_out["monte_carlo"]

    return result


def _run_multi_ogs_solve(
    req: MultiOGSSolveRequest,
    stations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Propagate orbit once, then run each station in sequence.

    Args:
        req:      Multi-OGS request (satellite/physics config).
        stations: Resolved list of station dicts (id, name, lat, lon, …).

    Returns:
        Dict with shared orbit info and per-station results.
    """
    logger.info(
        "Multi-OGS solve: a=%.1f km, inc=%.1f deg, %d stations",
        req.semi_major_axis, req.inclination_deg, len(stations),
    )

    # Build a SolveRequest stub so _build_cn2_layers and _run_single_station
    # can use the typed attribute accessors.
    stub = SolveRequest(
        semi_major_axis=req.semi_major_axis,
        eccentricity=req.eccentricity,
        inclination_deg=req.inclination_deg,
        raan_deg=req.raan_deg,
        arg_perigee_deg=req.arg_perigee_deg,
        mean_anomaly_deg=req.mean_anomaly_deg,
        j2_enabled=req.j2_enabled,
        j3_enabled=req.j3_enabled,
        j4_enabled=req.j4_enabled,
        epoch=req.epoch,
        samples_per_orbit=req.samples_per_orbit,
        total_orbits=req.total_orbits,
        sat_aperture_m=req.sat_aperture_m,
        ground_aperture_m=1.0,          # overridden per station
        wavelength_nm=req.wavelength_nm,
        qkd_protocol=req.qkd_protocol,
        photon_rate=req.photon_rate,
        detector_efficiency=req.detector_efficiency,
        dark_count_rate=req.dark_count_rate,
        pointing_error_urad=req.pointing_error_urad,
        scintillation_enabled=req.scintillation_enabled,
        scintillation_p0=req.scintillation_p0,
        atm_zenith_aod_db=req.atm_zenith_aod_db,
        atm_zenith_abs_db=req.atm_zenith_abs_db,
        fixed_optics_loss_db=req.fixed_optics_loss_db,
        link_direction=req.link_direction,
        pat_fading_enabled=req.pat_fading_enabled,
        dynamic_background_enabled=req.dynamic_background_enabled,
        min_elevation_deg=req.min_elevation_deg,
        elevation_threshold_deg=req.elevation_threshold_deg,
        background_enabled=req.background_enabled,
        background_Hrad_W_m2_sr_um=req.background_Hrad_W_m2_sr_um,
        background_fov_mrad=req.background_fov_mrad,
        background_delta_lambda_nm=req.background_delta_lambda_nm,
        temporal_gating_enabled=req.temporal_gating_enabled,
        gate_time_s=req.gate_time_s,
        sun_exclusion_deg=req.sun_exclusion_deg,
        tx_power_dbm=req.tx_power_dbm,
        rx_sensitivity_dbm=req.rx_sensitivity_dbm,
        atmosphere_model=req.atmosphere_model,
        ground_cn2_day=req.ground_cn2_day,
        ground_cn2_night=req.ground_cn2_night,
        finite_key_enabled=req.finite_key_enabled,
        epsilon_sec=req.epsilon_sec,
        epsilon_cor=req.epsilon_cor,
        basis_bias_qx=req.basis_bias_qx,
        p_signal=req.p_signal,
        p_decoy=req.p_decoy,
        # Availability: everything except the per-station hourly series, which
        # is substituted below.  A field omitted from this stub is silently
        # dropped, so the multi-station path would otherwise run with
        # availability off while the single-station path had it on.
        availability_enabled=req.availability_enabled,
        cloud_aspect_ratio=req.cloud_aspect_ratio,
        availability_estimator=req.availability_estimator,
        cloud_threshold_pct=req.cloud_threshold_pct,
        cloud_night_only=req.cloud_night_only,
        cloud_year=req.cloud_year,
        monte_carlo_enabled=req.monte_carlo_enabled,
        mc_realizations=req.mc_realizations,
        mc_seed=req.mc_seed,
        mc_quantiles=req.mc_quantiles,
    )

    # 1. Propagate orbit once ──────────────────────────────────────────
    prop = propagate_orbit(
        a=stub.semi_major_axis,
        e=stub.eccentricity,
        inc_deg=stub.inclination_deg,
        raan_deg=stub.raan_deg,
        arg_pe_deg=stub.arg_perigee_deg,
        M0_deg=stub.mean_anomaly_deg,
        j2_enabled=stub.j2_enabled,
        j3_enabled=stub.j3_enabled,
        j4_enabled=stub.j4_enabled,
        epoch_iso=stub.epoch,
        samples_per_orbit=stub.samples_per_orbit,
        total_orbits=stub.total_orbits,
    )

    orbit_info = {
        "semi_major_axis": prop["semi_major"],
        "period_s": prop["orbit_period"],
        "total_time_s": prop["total_time"],
        "samples": len(prop["data_points"]),
    }

    # 2. Run each station ─────────────────────────────────────────────
    station_results: List[Dict[str, Any]] = []
    hourly_by_station = req.cloud_cover_hourly_by_station or {}
    for s in stations:
        try:
            # Each station has its own climatology, so swap the injected series
            # per station.  A station absent from the map falls through to the
            # archive fetch, and to an explicit note if that fails.
            stub.cloud_cover_hourly = hourly_by_station.get(s.get("id", ""))
            out = _run_single_station(prop, s, stub)
            station_results.append({
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "lat": s["lat"],
                "lon": s["lon"],
                "altitude_m": s.get("altitude_m", 0.0),
                "aperture_m": s.get("aperture_m", 1.0),
                "qkd_summary": out.get("qkd_summary"),
                "key_volume": out.get("key_volume"),
                "monte_carlo": out.get("monte_carlo"),
            })
        except Exception as exc:
            logger.warning("Station %s failed: %s", s.get("id", "?"), exc, exc_info=True)
            station_results.append({
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "lat": s["lat"],
                "lon": s["lon"],
                "altitude_m": s.get("altitude_m", 0.0),
                "aperture_m": s.get("aperture_m", 1.0),
                "error": str(exc),
            })

    return {
        "orbit": orbit_info,
        "ground_track": prop["ground_track"],
        "timeline": prop["timeline"],
        "stations": station_results,
        "station_count": len(station_results),
    }


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


@router.post("/solve/multi-ogs")
async def solve_multi_ogs(req: MultiOGSSolveRequest):
    """Run the same satellite simulation over multiple ground stations.

    Propagates the orbit once and evaluates link geometry, loss, QKD key
    rate, and key volume for every requested station.  Stations can be
    referenced by their store ID (``station_ids``) or provided inline
    (``inline_stations``); both lists are merged.

    Returns:
        Shared orbit info + per-station ``qkd_summary`` and ``key_volume``
        dicts suitable for building comparison tables and plots.
    """
    stations = resolve_stations(req.station_ids, req.inline_stations)

    try:
        return await run_in_threadpool(_run_multi_ogs_solve, req, stations)
    except Exception as exc:
        raise HTTPException(500, f"Multi-OGS solver error: {exc}") from exc
