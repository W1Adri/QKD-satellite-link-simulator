# ---------------------------------------------------------------------------
# app/routers/study.py
# ---------------------------------------------------------------------------
# Purpose : Constellation-over-network study endpoint — the engine behind the
#           conference case study (Walker constellation over the European OGS
#           network).
#
#           WHY A SEPARATE ENDPOINT.  /api/solve is one satellite; extending it
#           would break its single-satellite response contract and the frontend
#           that consumes it.  /api/paper/constellation is the Ntanos et al.
#           2021 reproduction and must stay frozen at the paper's parameters to
#           remain comparable.  This is the third thing: an arbitrary
#           constellation over an arbitrary network, with contention accounted
#           for and finite-key applied to what a scheduler actually served.
#
#           WHY IT REUSES _run_single_station.  Every satellite-station pair is
#           evaluated by the SAME function /api/solve calls, not by a parallel
#           implementation.  A study whose physics has silently drifted from the
#           simulator it claims to use is not reproducible, and a second copy of
#           the link budget drifts the moment either is touched.
#
#           WHAT IS NEW HERE.  Two things the per-pair numbers cannot express:
#
#           1. CONTENTION.  One optical terminal per satellite and one telescope
#              per station means the visible pairs form a bipartite graph of
#              which only a matching is servable.  Summing all pairs answers a
#              question no operator can ask, and makes the marginal value of the
#              (N+1)-th station trivially equal to its standalone key.  Under
#              the matching constraint that value saturates — and where it
#              saturates is the result.  See physics/scheduling.py.
#
#           2. FINITE KEY ON WHAT WAS ACTUALLY SERVED.  A schedule that hands a
#              pair half a pass does not hand it half the key: the Lim et al.
#              2014 statistical deviations scale as sqrt(n) while the counts
#              scale as n, so a fragmented pass must be re-evaluated over the
#              served intervals rather than pro-rated.  This is why the
#              preemptive policy — an upper bound in asymptotic key — can be
#              BEATEN by the non-preemptive one once finite-key is on: it wins
#              the instantaneous rate contest by shattering passes into blocks
#              too small to distil from.  That inversion is the headline result
#              and it requires both modules on one code path.
#
# References:
#   Lim, Curty, Walenta, Xu, Zbinden, PRA 89, 022307 (2014) — finite-key decoy.
#   Kuhn (1955) / Munkres (1957) — assignment problem (preemptive optimum).
#   Kleinberg & Tardos (2005) §6.1 — weighted interval scheduling DP (bound).
#   Nemhauser, Wolsey & Fisher, Math. Program. 14, 265 (1978) — greedy on a
#     monotone submodular objective, which is what makes the marginal curve's
#     knee meaningful.
#   Walker, J. Br. Interplanet. Soc. 37, 559 (1984) — Walker-Delta T/P/F.
#
# Endpoints:
#   POST /api/study/constellation – M satellites x N stations, contention-aware
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..models import OGSLocation, SolveRequest
from ..physics.propagation import propagate_orbit
from ..physics.scheduling import (
    Contact,
    contact_upper_bound,
    contacts_from_elevation,
    interval_weights,
    marginal_curve,
    schedule_contacts,
    schedule_independent,
    schedule_preemptive,
)
from ..physics.walker import generate_walker
from .solver import _run_single_station, resolve_stations

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/study", tags=["study"])

POLICIES = ("independent", "preemptive", "contact")


# ── Request model ──────────────────────────────────────────────────────────

class ConstellationStudyRequest(BaseModel):
    """Payload for POST /api/study/constellation.

    ``base`` carries every physics, QKD, finite-key and availability setting,
    exactly as /api/solve consumes them, plus the orbit template (eccentricity,
    epoch, samples_per_orbit, total_orbits).  The per-satellite elements
    override only what a constellation must vary: semi-major axis, inclination,
    RAAN and mean anomaly.  Nothing else is re-specified here, so a study run
    and a single-link run of the same configuration cannot disagree.
    """

    base: SolveRequest = Field(
        description="Physics/QKD/orbit template applied to every satellite")

    # ── Constellation: Walker-Delta, or an explicit element list ───────────
    walker_T: Optional[int] = Field(default=None, ge=1, le=200,
                                    description="Total satellites")
    walker_P: Optional[int] = Field(default=None, ge=1, le=50,
                                    description="Orbital planes")
    walker_F: int = Field(default=1, ge=0, description="Phasing parameter")
    altitude_km: Optional[float] = Field(default=None, gt=100.0, le=40000.0)
    inclination_deg: Optional[float] = Field(default=None, ge=0.0, le=180.0)
    raan_offset_deg: float = Field(default=0.0)
    # Explicit elements win over the Walker parameters when both are supplied.
    satellites: Optional[List[Dict[str, float]]] = Field(
        default=None,
        description="Explicit element dicts (semiMajor, eccentricity, "
                    "inclination, raan, argPerigee, meanAnomaly); overrides "
                    "the Walker parameters")

    # ── Network ────────────────────────────────────────────────────────────
    station_ids: Optional[List[str]] = None
    inline_stations: Optional[List[OGSLocation]] = None

    # ── Contention ─────────────────────────────────────────────────────────
    policies: List[str] = Field(default=list(POLICIES))
    sat_terminals: int = Field(default=1, ge=1, le=8,
                               description="Optical terminals per satellite")
    gs_terminals: int = Field(default=1, ge=1, le=8,
                              description="Telescopes per ground station")

    # ── Marginal-value curve ───────────────────────────────────────────────
    marginal_over: Optional[str] = Field(
        default=None,
        description="'stations' | 'satellites' | None. O(n^2) schedule "
                    "evaluations under the greedy order — keep n modest.")
    marginal_order: str = Field(default="greedy",
                                description="greedy | given | standalone")
    marginal_policy: str = Field(
        default="contact",
        description="Policy the marginal curve is evaluated under. 'contact' "
                    "is the meaningful one: under 'independent' every marginal "
                    "gain is the standalone value by construction.")
    marginal_metric: str = Field(
        default="finite",
        description="'finite' | 'asymptotic' — which total the curve tracks.")

    # ── Output size control ────────────────────────────────────────────────
    include_series: bool = Field(
        default=False,
        description="Return the per-pair key-rate time series. Off by default: "
                    "M x N dense series is megabytes.")


# ── Per-pair evaluation ────────────────────────────────────────────────────

def _build_elements(req: ConstellationStudyRequest) -> List[Dict[str, float]]:
    """Resolve the request into a list of Keplerian element dicts."""
    if req.satellites:
        return [dict(s) for s in req.satellites]

    if req.walker_T is None or req.walker_P is None:
        raise HTTPException(
            400,
            "Provide either 'satellites' or both 'walker_T' and 'walker_P'")
    if req.walker_T % req.walker_P != 0:
        raise HTTPException(
            400,
            f"Walker T={req.walker_T} is not divisible by P={req.walker_P}; "
            "generate_walker would silently drop satellites")

    from ..physics.constants import EARTH_RADIUS_KM

    alt = req.altitude_km
    if alt is None:
        alt = float(req.base.semi_major_axis) - EARTH_RADIUS_KM
    inc = req.inclination_deg
    if inc is None:
        inc = float(req.base.inclination_deg)

    elems = generate_walker(
        req.walker_T, req.walker_P, req.walker_F, alt, inc,
        eccentricity=float(req.base.eccentricity),
        raan_offset_deg=req.raan_offset_deg,
    )
    if not elems:
        raise HTTPException(400, "Walker generation produced no satellites")
    return elems


def _propagate_all(
    elements: Sequence[Dict[str, float]],
    base: SolveRequest,
) -> List[Dict[str, Any]]:
    """Propagate every satellite on the SAME time grid.

    The scheduler compares pairs interval by interval, so every satellite must
    be sampled at identical instants.  propagate_orbit derives the window from
    the orbital period, so a constellation whose members differ in semi-major
    axis would produce different grids; that is rejected rather than silently
    resampled, because interpolating a link budget across a re-grid is exactly
    the kind of quiet error a reviewer cannot see.
    """
    sma = {round(float(e["semiMajor"]), 6) for e in elements}
    if len(sma) > 1:
        raise HTTPException(
            400,
            "All satellites must share a semi-major axis so the scheduler sees "
            f"one common time grid; got {sorted(sma)}")

    props = []
    for e in elements:
        props.append(propagate_orbit(
            a=float(e["semiMajor"]),
            e=float(e.get("eccentricity", 0.0)),
            inc_deg=float(e["inclination"]),
            raan_deg=float(e["raan"]),
            arg_pe_deg=float(e.get("argPerigee", 0.0)),
            M0_deg=float(e.get("meanAnomaly", 0.0)),
            j2_enabled=base.j2_enabled,
            j3_enabled=base.j3_enabled,
            j4_enabled=base.j4_enabled,
            epoch_iso=base.epoch,
            samples_per_orbit=base.samples_per_orbit,
            total_orbits=base.total_orbits,
        ))
    return props


def _pair_rates_bps(
    metrics: Dict[str, Any],
    n_pts: int,
    elevation_threshold_deg: float,
) -> np.ndarray:
    """Dense secret-key rate in bit/s, zero wherever the link is unusable.

    The elevation threshold is applied HERE, to the rate series every policy is
    scored from, and not only inside the contact segmentation.  Otherwise the
    preemptive policy — which works interval by interval and never looks at
    contacts — would be free to collect key from samples below the minimum
    tracking elevation that the non-preemptive policy is forbidden to touch.
    The two would then be solving different problems and the bound chain
    comparing them would be meaningless: preemptive's total stayed constant
    while contact's fell as the threshold rose.
    """
    out = np.zeros(n_pts, dtype=float)
    series = metrics.get("skrKbps") or []
    elev = metrics.get("elevationDeg") or []
    for i, v in enumerate(series[:n_pts]):
        if v is None or v <= 0:
            continue
        e = elev[i] if i < len(elev) else None
        if e is None or e < elevation_threshold_deg:
            continue
        out[i] = float(v) * 1e3
    return out


# ── Finite key over served fragments ───────────────────────────────────────

def _finite_bits_for_fragments(
    fragments: Sequence[Tuple[int, int]],
    contacts: Sequence[Contact],
    evaluate,
) -> float:
    """Re-derive the finite key for one pair from the intervals it was served.

    Fragments are grouped BY CONTACT before evaluation, because the published
    convention is one pass = one block (Islam et al., PRX Quantum 5, 030101
    (2024) §III B).  Two fragments of the same pass are one block whose counts
    are the sum over both; two fragments of different passes are two blocks,
    each paying its own sqrt(n) deviation.  Merging across passes would
    manufacture key that no receiver could distil, since the blocks are hours
    apart and the error correction is per pass.
    """
    if evaluate is None or not fragments:
        return 0.0
    total = 0.0
    for c in contacts:
        served = [
            (max(a, c.i0), min(b, c.i1))
            for (a, b) in fragments
            if a <= c.i1 and c.i0 <= b
        ]
        served = [(a, b) for (a, b) in served if b > a]
        if not served:
            continue
        out = evaluate(served)
        if out:
            total += float(out.get("ellFiniteBits", 0.0) or 0.0)
    return total


# ── Study driver ───────────────────────────────────────────────────────────

def _run_constellation_study(
    req: ConstellationStudyRequest,
    stations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate every pair, then score each contention policy over the result."""
    elements = _build_elements(req)
    props = _propagate_all(elements, req.base)
    n_sat = len(elements)
    n_gs = len(stations)
    timeline = props[0]["timeline"]
    n_pts = len(timeline)
    threshold = float(req.base.elevation_threshold_deg)

    logger.info("Constellation study: %d sats x %d stations, %d samples",
                n_sat, n_gs, n_pts)

    rates: Dict[Tuple[int, int], np.ndarray] = {}
    elevs: Dict[Tuple[int, int], List[Optional[float]]] = {}
    evaluators: Dict[Tuple[int, int], Any] = {}
    pair_summary: Dict[str, Dict[str, Any]] = {}
    series_out: Dict[str, Any] = {}

    for si in range(n_sat):
        for gi, st in enumerate(stations):
            out = _run_single_station(
                props[si], st, req.base,
                collect_fk_evaluator=bool(req.base.finite_key_enabled),
            )
            m = out["station_metrics"]
            pair = (si, gi)
            rates[pair] = _pair_rates_bps(m, n_pts, threshold)
            elevs[pair] = m["elevationDeg"]
            evaluators[pair] = out.get("_fk_evaluate")
            kv = out.get("key_volume") or {}
            pair_summary[f"sat{si + 1}|{st.get('id') or f'gs{gi}'}"] = {
                "passes": kv.get("pass_count", 0),
                "key_mb_unscheduled": kv.get("total_key_volume_mb", 0.0),
                "peak_skr_kbps": (out.get("qkd_summary") or {}).get(
                    "peak_skr_kbps", 0.0),
            }
            if req.include_series:
                series_out[f"sat{si + 1}|{st.get('id') or f'gs{gi}'}"] = {
                    "skrKbps": m.get("skrKbps"),
                    "elevationDeg": m.get("elevationDeg"),
                }

    # Per-interval bits, then contacts, on the shared grid.
    weights, active = interval_weights(timeline, rates)
    contacts_by_pair: Dict[Tuple[int, int], List[Contact]] = {}
    all_contacts: List[Contact] = []
    for pair, w in weights.items():
        cs = contacts_from_elevation(
            pair[0], pair[1], timeline, elevs[pair], w, threshold)
        contacts_by_pair[pair] = cs
        all_contacts.extend(cs)

    fk_on = bool(req.base.finite_key_enabled) and any(
        e is not None for e in evaluators.values())

    def _score(policy: str, sats: Sequence[int], gss: Sequence[int]) -> Dict[str, Any]:
        """Run one policy restricted to a subset of satellites and stations."""
        sub_w = {p: w for p, w in weights.items()
                 if p[0] in set(sats) and p[1] in set(gss)}
        if not sub_w:
            return {"policy": policy, "asymptotic_bits": 0.0,
                    "finite_bits": 0.0 if fk_on else None,
                    "contacts_served": 0, "notes": []}
        sub_contacts = [c for c in all_contacts
                        if c.sat in set(sats) and c.gs in set(gss)]

        if policy == "independent":
            res = schedule_independent(sub_w, active)
        elif policy == "preemptive":
            res = schedule_preemptive(
                sub_w, active, len(sats), len(gss),
                sat_terminals=req.sat_terminals, gs_terminals=req.gs_terminals)
        elif policy == "contact":
            res = schedule_contacts(
                sub_contacts,
                sat_terminals=req.sat_terminals, gs_terminals=req.gs_terminals)
        else:
            raise HTTPException(400, f"Unknown policy '{policy}'")

        rec: Dict[str, Any] = {
            "policy": policy,
            "asymptotic_bits": res.total_bits,
            "asymptotic_mb": res.total_bits / 8e6,
            # Whole contacts for the non-preemptive policy; for the others a
            # pair may be served in several pieces, so count the pieces — the
            # gap between this and `contacts.total` IS the fragmentation the
            # finite-key column then pays for.
            "contacts_served": (
                len(res.contacts_kept) if res.contacts_kept
                else sum(len(f) for f in res.fragments.values())
            ),
            "notes": list(res.notes),
        }
        if fk_on:
            fin = 0.0
            for pair, frags in res.fragments.items():
                fin += _finite_bits_for_fragments(
                    frags, contacts_by_pair.get(pair, []), evaluators.get(pair))
            rec["finite_bits"] = fin
            rec["finite_mb"] = fin / 8e6
            rec["finite_fraction"] = (fin / res.total_bits) if res.total_bits > 0 else 0.0
        return rec

    all_sats = list(range(n_sat))
    all_gss = list(range(n_gs))

    requested = [p for p in req.policies if p in POLICIES]
    if not requested:
        raise HTTPException(400, f"No valid policy requested; pick from {POLICIES}")
    scored = {p: _score(p, all_sats, all_gss) for p in requested}

    bound = contact_upper_bound(
        all_contacts,
        sat_terminals=req.sat_terminals, gs_terminals=req.gs_terminals)

    result: Dict[str, Any] = {
        "constellation": {
            "n_sats": n_sat,
            "walker": ({"T": req.walker_T, "P": req.walker_P, "F": req.walker_F}
                       if req.satellites is None else None),
            "altitude_km": round(
                float(elements[0]["semiMajor"]) - 6378.137, 3),
            "inclination_deg": float(elements[0]["inclination"]),
        },
        "stations": [
            {"index": i, "id": s.get("id", ""), "name": s.get("name", ""),
             "lat": s["lat"], "lon": s["lon"],
             "aperture_m": s.get("aperture_m", req.base.ground_aperture_m)}
            for i, s in enumerate(stations)
        ],
        "window": {
            "orbits": req.base.total_orbits,
            "samples": n_pts,
            "duration_s": float(timeline[-1]) if n_pts else 0.0,
            "period_s": props[0]["orbit_period"],
        },
        "contacts": {
            "total": len(all_contacts),
            "elevation_threshold_deg": threshold,
        },
        "policies": scored,
        "contact_upper_bound": bound,
        "pairs": pair_summary,
        "finite_key": {
            "enabled": fk_on,
            "note": (
                "Finite key is re-derived over the intervals each policy "
                "actually served, grouped by pass (one pass = one block). It "
                "is NOT the per-pass key pro-rated: Lim 2014 deviations scale "
                "as sqrt(n) while counts scale as n, so a fragmented pass "
                "keeps less than its time share — and below a threshold block "
                "size it keeps nothing."
            ) if fk_on else (
                "Asymptotic only: set base.finite_key_enabled and a "
                "decoy-state protocol to get the finite-key columns."
            ),
        },
    }

    # Bound chain, stated explicitly so the ordering can be checked rather
    # than assumed — and so the finite-key inversion is visible when it happens.
    chain: Dict[str, Any] = {}
    if "contact" in scored:
        chain["contact_greedy"] = scored["contact"]["asymptotic_bits"]
    chain["contact_opt_upper_bound"] = bound["bound"]
    if "preemptive" in scored:
        chain["preemptive"] = scored["preemptive"]["asymptotic_bits"]
    if "independent" in scored:
        chain["independent"] = scored["independent"]["asymptotic_bits"]
    result["bound_chain_asymptotic"] = chain

    if fk_on and "preemptive" in scored and "contact" in scored:
        pre, con = scored["preemptive"]["finite_bits"], scored["contact"]["finite_bits"]
        result["finite_key_inversion"] = {
            "preemptive_finite_bits": pre,
            "contact_finite_bits": con,
            "inverted": con > pre,
            "note": (
                "Inverted: the preemptive schedule delivers more ASYMPTOTIC "
                "key but less FINITE key, because re-pointing mid-pass "
                "fragments blocks below the size at which they can be "
                "distilled. The asymptotic upper bound is therefore not an "
                "upper bound on deliverable key."
                if con > pre else
                "Not inverted at this configuration: the preemptive schedule "
                "still wins after finite-key correction. The inversion "
                "appears when contention forces fragmentation — try more "
                "satellites per station, or a shorter pass."
            ),
        }

    if req.sat_terminals > 1 or req.gs_terminals > 1:
        result.setdefault("caveats", []).append(
            "With more than one terminal per node the preemptive policy "
            "reduces b-matching to matching by replicating rows/columns and "
            "then discards duplicate pair selections; the result is a valid "
            "schedule but no longer the exact b-matching optimum, so it is "
            "reported as a lower bound on the preemptive relaxation. The "
            "contact upper bound likewise falls back to a loose relaxation "
            "(see contact_upper_bound.note)."
        )

    # ── Marginal-value curve ──────────────────────────────────────────────
    if req.marginal_over in ("stations", "satellites"):
        pol = req.marginal_policy
        if pol not in POLICIES:
            raise HTTPException(400, f"Unknown marginal_policy '{pol}'")
        metric = "finite_bits" if (req.marginal_metric == "finite" and fk_on) \
            else "asymptotic_bits"

        if req.marginal_over == "stations":
            elems_m: List[Any] = all_gss
            def _ev(subset: Sequence[Any]) -> float:
                return float(_score(pol, all_sats, list(subset))[metric] or 0.0)
        else:
            elems_m = all_sats
            def _ev(subset: Sequence[Any]) -> float:
                return float(_score(pol, list(subset), all_gss)[metric] or 0.0)

        curve = marginal_curve(elems_m, _ev, order=req.marginal_order)
        label = (lambda i: stations[i].get("id") or stations[i].get("name") or f"gs{i}") \
            if req.marginal_over == "stations" else (lambda i: f"sat{i + 1}")
        result["marginal_curve"] = {
            "over": req.marginal_over,
            "policy": pol,
            "metric": metric,
            "order": req.marginal_order,
            "steps": [
                {**s, "element": label(s["index"])} for s in curve
            ],
            "note": (
                "'saturation' is the marginal gain as a fraction of that "
                "element's standalone value: 1.0 means it added everything it "
                "is worth, 0.0 means the network already covered it. Under the "
                "'independent' policy it is 1.0 everywhere by construction, "
                "which is exactly why that policy cannot answer this question."
            ),
        }

    if req.include_series:
        result["series"] = series_out

    return result


# ── Endpoint ───────────────────────────────────────────────────────────────

@router.post("/constellation")
async def constellation_study(req: ConstellationStudyRequest):
    """Run a constellation over a ground-station network with contention.

    Evaluates every satellite-station pair through the same physics path as
    /api/solve, then scores three contention policies over the shared timeline
    and reports the bound chain

        contact_greedy <= contact_OPT <= min(ub_sat, ub_gs)
                       <= preemptive <= independent

    together with the finite-key total each policy actually delivers.
    """
    stations = resolve_stations(req.station_ids, req.inline_stations)
    try:
        return await run_in_threadpool(_run_constellation_study, req, stations)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Constellation study failed")
        raise HTTPException(500, f"Constellation study error: {exc}") from exc
