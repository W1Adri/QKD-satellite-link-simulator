# ---------------------------------------------------------------------------
# app/physics/key_volume.py
# ---------------------------------------------------------------------------
# Purpose : Per-pass key volume integration (SYS-01) and daily key volume
#           aggregation (SYS-02).  Converts the instantaneous key rate
#           time-series from /api/solve into physically meaningful pass-level
#           and daily aggregates — the metric QKD researchers use to assess
#           real-world link feasibility.
#
# References:
#   Liao et al., Nature 549, 43 (2017) — key volume = integral of R(t) over
#   pass duration; https://doi.org/10.1038/nature23655
#
# Exports:
#   segment_passes(elevation_deg, threshold_deg) -> list[tuple[int,int]]
#   compute_key_volume(timeline, link_established, elevation_deg,
#                      qkd_per_sample, epoch_iso,
#                      elevation_threshold_deg, *, pass_hook,
#                      availability_profile, availability_beta) -> dict
#   aggregate_daily_mb(passes, epoch_iso) -> dict[str, float]
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── Pass segmentation ────────────────────────────────────────────────────────

def segment_passes(
    elevation_deg: list[float],
    threshold_deg: float = 5.0,
) -> list[tuple[int, int]]:
    """Find contiguous above-threshold segments in an elevation array.

    Single-sample blips (only 1 consecutive sample above threshold) are
    discarded to avoid spurious pass detections at the horizon.

    Args:
        elevation_deg: Per-sample elevation in degrees (length N).
        threshold_deg: Minimum elevation to count as an "in-view" sample.

    Returns:
        List of (start_idx, end_idx) tuples (inclusive) for each valid pass.
    """
    passes: list[tuple[int, int]] = []
    n = len(elevation_deg)
    i = 0
    while i < n:
        if elevation_deg[i] is not None and elevation_deg[i] > threshold_deg:
            start = i
            while i < n and elevation_deg[i] is not None and elevation_deg[i] > threshold_deg:
                i += 1
            end = i - 1  # inclusive
            # Skip single-sample blips
            if end > start:
                passes.append((start, end))
        else:
            i += 1
    return passes


# ── Daily aggregation ────────────────────────────────────────────────────────

def aggregate_daily_mb(
    passes: list[dict],
    epoch_iso: str,
) -> dict[str, float]:
    """Accumulate key volume (MB) per UTC calendar day.

    Args:
        passes: List of pass dicts (each must have 'pass_start_s' and
                'key_volume_mb' keys).
        epoch_iso: ISO-8601 epoch string for the simulation start (e.g.
                   "2026-03-30T00:00:00Z").

    Returns:
        Dict mapping "YYYY-MM-DD" strings to total MB for that day.
    """
    if not epoch_iso:
        # No epoch → bucket by offset day index only
        daily: dict[str, float] = {}
        for p in passes:
            day_idx = int(p["pass_start_s"] // 86400)
            key = f"day_{day_idx}"
            daily[key] = daily.get(key, 0.0) + p["key_volume_mb"]
        return daily

    try:
        epoch_dt = datetime.fromisoformat(epoch_iso.replace("Z", "+00:00"))
    except ValueError:
        epoch_dt = datetime.now(tz=timezone.utc)

    daily: dict[str, float] = {}
    for p in passes:
        utc_dt = epoch_dt + timedelta(seconds=p["pass_start_s"])
        date_key = utc_dt.strftime("%Y-%m-%d")
        daily[date_key] = daily.get(date_key, 0.0) + p["key_volume_mb"]
    return daily


# ── Cloud availability composition ───────────────────────────────────────────

def _pass_month(epoch_iso: str, pass_start_s: float) -> Optional[int]:
    """Calendar month (1-12) of a pass, or None without a usable epoch.

    Same arithmetic as :func:`aggregate_daily_mb`: absolute time is always the
    epoch string plus elapsed seconds.  Returning None is meaningful — the
    availability layer answers it with the annual statistic rather than
    guessing a month.
    """
    if not epoch_iso:
        return None
    try:
        epoch_dt = datetime.fromisoformat(epoch_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if epoch_dt.tzinfo is None:
        epoch_dt = epoch_dt.replace(tzinfo=timezone.utc)
    return (epoch_dt + timedelta(seconds=pass_start_s)).month


def _trapezoid_weights(t_slice) -> list[float]:
    """Per-sample weights that reproduce ``np.trapezoid`` as a plain sum.

    Using these as the reduction weights makes the key-weighted availability
    EXACTLY consistent with the integral computed alongside it: with
    ``p_bar = sum w_i p_i k_i / sum w_i k_i`` and
    ``volume = sum w_i k_i``, the product ``p_bar * volume`` is precisely the
    trapezoid integral of ``p(t) R(t)``.  A uniform grid (which
    ``physics.propagation`` happens to produce) would make plain averaging
    equivalent, but relying on that would silently break for any other grid.
    """
    n = len(t_slice)
    if n < 2:
        return [0.0] * n
    w = [0.0] * n
    w[0] = (float(t_slice[1]) - float(t_slice[0])) / 2.0
    w[-1] = (float(t_slice[-1]) - float(t_slice[-2])) / 2.0
    for i in range(1, n - 1):
        w[i] = (float(t_slice[i + 1]) - float(t_slice[i - 1])) / 2.0
    return w


def _apply_availability(
    entry: dict,
    profile_src,
    beta: float,
    elev_slice,
    rate_slice,
    t_slice,
    volume_mb: float,
    fk_fraction: Optional[float],
    month: Optional[int],
) -> None:
    """Attach the cloud-availability factor and the composed volumes to a pass.

    The reduction is key-rate weighted over the pass, so it is the expected
    clear fraction of the KEY rather than of the time — and it uses trapezoid
    weights, so ``keyVolumeAvailable`` is exactly the integral of
    ``P_CFLOS(eps(t)) * R(t)`` over the pass.
    """
    from .availability import effective_key_mb, pass_availability

    try:
        profile = profile_src(month) if callable(profile_src) else profile_src
        av = pass_availability(elev_slice, rate_slice, profile, beta=beta,
                               dt_s=_trapezoid_weights(t_slice))
    except Exception:
        logger.warning(
            "availability reduction failed for pass at %.1f s — pass reported "
            "without a cloud factor", entry.get("pass_start_s", 0.0),
            exc_info=True,
        )
        return

    entry["passMonth"] = month
    entry["availability"] = av["keyWeighted"]
    entry["availabilityDetail"] = av
    entry["keyVolumeAvailable"] = volume_mb * av["keyWeighted"]
    if fk_fraction is not None:
        # The one place the three factors meet, so each is applied exactly once.
        entry["keyVolumeExpected"] = effective_key_mb(
            volume_mb, fk_fraction, av["keyWeighted"])
        ell = entry.get("ellFiniteBits")
        if ell is not None:
            entry["ellExpectedBits"] = float(ell) * av["keyWeighted"]


# ── Key volume integration ───────────────────────────────────────────────────

def compute_key_volume(
    timeline: list[float],
    link_established: list[bool],
    elevation_deg: list[float],
    qkd_per_sample: list[dict],
    epoch_iso: str,
    elevation_threshold_deg: float = 5.0,
    *,
    pass_hook=None,
    availability_profile=None,
    availability_beta: float = 1.0,
) -> dict:
    """Integrate per-pass key volume from the QKD key-rate time-series.

    Algorithm (Liao et al., Nature 549, 43 (2017)):
    1. Build a dense rate array (bit/s) of length N from the sparse
       qkd_per_sample list (which only has entries where link was active).
    2. Clamp negative rates to 0 (D-02).
    3. Zero out samples where linkEstablished is False (D-01).
    4. Use np.trapz to numerically integrate each pass segment.
    5. Convert integrated bits to MB (÷ 8 ÷ 1e6).
    6. Aggregate by UTC calendar day.

    Args:
        timeline:             Array of time offsets in seconds (length N).
        link_established:     Bool array (length N) — link up/down per sample.
        elevation_deg:        Elevation angle in degrees (length N).
        qkd_per_sample:       Sparse list; each item must have 't' (seconds)
                              and 'secureKeyRate' (kbit/s).
        epoch_iso:            ISO-8601 epoch string for the simulation start.
        elevation_threshold_deg: Elevation threshold for pass boundary (deg).
        pass_hook:            Optional ``callable(start_idx, end_idx) -> dict``
                              invoked once per detected pass with the inclusive
                              sample-index range of that pass.  Whatever dict it
                              returns is merged into the pass result.  This is
                              how per-pass finite-key analysis attaches itself
                              (see routers/solver.py): pass segmentation stays
                              defined in exactly one place, and the caller,
                              which is the only thing that knows the protocol,
                              accumulates its own per-sample series over the
                              same window.
        availability_profile: Optional cloud-availability profile from
                              ``physics.availability.pcflos_profile`` — either a
                              single profile dict applied to every pass, or a
                              ``callable(month: int | None) -> profile``.  Each
                              pass is reduced against its own elevation and key
                              -rate arrays, so the factor sits INSIDE the pass
                              sum where the positive covariance between
                              elevation and key rate belongs.  The availability
                              result lives in its own keys and NEVER touches
                              ``key_volume_mb`` / ``keyVolumeFinite``: those
                              stay pure clear-sky, and ``mean_fk_fraction`` is
                              back-derived from the finite/asymptotic ratio, so
                              folding a cloud factor into it would silently
                              report ``fk x availability`` as the finite-key
                              penalty.
        availability_beta:    Cloud aspect ratio, forwarded for the reported
                              mean shape factor only.

    Returns:
        Dict with keys: passes, pass_count, total_key_volume_mb,
        daily_mb, elevation_threshold_deg.  When *pass_hook* supplies
        ``keyVolumeFinite`` per pass, also ``total_key_volume_finite_mb`` and
        ``mean_fk_fraction`` (key-weighted).  When *availability_profile* is
        given, also ``total_key_volume_available_mb``, ``mean_availability``
        (key-weighted) and — with finite key on —
        ``total_key_volume_expected_mb`` and ``total_key_bits_expected_lim``.
    """
    n = len(timeline)
    if n == 0:
        return {
            "passes": [],
            "pass_count": 0,
            "total_key_volume_mb": 0.0,
            "daily_mb": {},
            "elevation_threshold_deg": elevation_threshold_deg,
        }

    t_arr = np.asarray(timeline, dtype=float)
    rate_arr = np.zeros(n, dtype=float)

    # --- Populate dense rate array from sparse qkd_per_sample ---------------
    for sample in qkd_per_sample:
        t_val = float(sample.get("t", 0.0))
        skr = float(sample.get("secureKeyRate", 0.0))
        idx = int(np.searchsorted(t_arr, t_val))
        if 0 <= idx < n:
            # kbit/s → bit/s; clamp negative to 0 (D-02)
            rate_arr[idx] = max(0.0, skr * 1000.0)

    # --- Zero samples where link is not established (D-01) ------------------
    for i in range(n):
        if not link_established[i]:
            rate_arr[i] = 0.0

    # --- Segment passes and integrate ---------------------------------------
    segs = segment_passes(elevation_deg, elevation_threshold_deg)
    pass_results: list[dict] = []

    for start, end in segs:
        t_slice = t_arr[start : end + 1]
        r_slice = rate_arr[start : end + 1]
        volume_bits = float(np.trapezoid(r_slice, t_slice))
        volume_mb = volume_bits / (8.0 * 1e6)
        entry = {
            "pass_start_s": float(t_slice[0]),
            "pass_end_s":   float(t_slice[-1]),
            "duration_s":   float(t_slice[-1] - t_slice[0]),
            "key_volume_bits": volume_bits,
            "key_volume_mb":   volume_mb,
        }
        frac = None
        if pass_hook is not None:
            try:
                extra = pass_hook(start, end)
            except Exception:
                logger.warning(
                    "pass_hook failed for pass [%d, %d] — pass reported without "
                    "its extra fields", start, end, exc_info=True,
                )
                extra = None
            if extra:
                entry.update(extra)
                # Scale the asymptotic volume by the finite-size penalty.  Done
                # here rather than in the hook so the multiplication always
                # applies to exactly the integral computed just above.
                frac = extra.get("fkFraction")
                if frac is not None:
                    entry["keyVolumeFinite"] = volume_mb * float(frac)

        if availability_profile is not None:
            _apply_availability(
                entry, availability_profile, availability_beta,
                elevation_deg[start : end + 1], r_slice, t_slice,
                volume_mb, frac,
                _pass_month(epoch_iso, float(t_slice[0])),
            )
        pass_results.append(entry)

    total_mb = sum(p["key_volume_mb"] for p in pass_results)
    daily = aggregate_daily_mb(pass_results, epoch_iso)

    logger.debug(
        "key_volume: %d passes, total=%.6f MB, threshold=%.1f deg",
        len(pass_results), total_mb, elevation_threshold_deg,
    )

    out = {
        "passes": pass_results,
        "pass_count": len(pass_results),
        "total_key_volume_mb": total_mb,
        "daily_mb": daily,
        "elevation_threshold_deg": elevation_threshold_deg,
    }

    if any("keyVolumeFinite" in p for p in pass_results):
        total_fin = sum(p.get("keyVolumeFinite", 0.0) for p in pass_results)
        out["total_key_volume_finite_mb"] = total_fin
        # Key-weighted, not per-pass mean: an unweighted mean would let empty
        # passes drag the reported penalty around.
        out["mean_fk_fraction"] = (total_fin / total_mb) if total_mb > 0 else 0.0
        out["total_key_bits_finite_lim"] = sum(
            p.get("ellFiniteBits", 0.0) for p in pass_results
        )

    if any("availability" in p for p in pass_results):
        total_av = sum(p.get("keyVolumeAvailable", 0.0) for p in pass_results)
        out["total_key_volume_available_mb"] = total_av
        # Key-weighted like mean_fk_fraction, and deliberately derived from the
        # availability-only total so the two penalties stay separable.
        out["mean_availability"] = (total_av / total_mb) if total_mb > 0 else 0.0
        if any("keyVolumeExpected" in p for p in pass_results):
            out["total_key_volume_expected_mb"] = sum(
                p.get("keyVolumeExpected", 0.0) for p in pass_results
            )
            # The paper's headline number: sum_i p_CFLOS,i * ell_i, i.e. the
            # rigorous Lim 2014 key length weighted by cloud availability.
            out["total_key_bits_expected_lim"] = sum(
                p.get("ellExpectedBits", 0.0) for p in pass_results
            )

    return out
