# ---------------------------------------------------------------------------
# app/physics/availability.py
# ---------------------------------------------------------------------------
# Purpose : Cloud availability of an optical ground station — PCFLOS
#           (Probability of Cloud-Free Line Of Sight) as an ELEVATION-RESOLVED,
#           per-month, optionally night-conditioned factor, plus the
#           composition rules for folding it into a per-pass key volume.
#
#           Pure functions only: no network, no file I/O.  Fetching and
#           caching the underlying reanalysis data is the job of
#           services/pcflos_svc.py.  This split matters because the study
#           results must be reproducible from a cached table without touching
#           the network.
#
# THE MODEL (one line of physics, three independent supports)
#
#     P_CFLOS(eps) = (1 - N) ** f(eps),      f(eps) = sqrt(1 + beta^2 cot^2 eps)
#
#   N    = absolute (vertically projected) cloud fraction — exactly what ERA5
#          total cloud cover estimates for a grid cell.
#   eps  = link elevation angle; the zenith angle is theta = 90 deg - eps, so
#          tan theta = cot eps.
#   beta = cloud aspect ratio h/(2r) (height over horizontal diameter).
#
#   * At zenith f = 1 and the model collapses to P = 1 - N, which is the exact
#     nadir identity [Reinke & Vonder Haar] and also the availability
#     definition used by the two published satellite-QKD precedents
#     [Anipeddi 2025; Hossain 2025].
#   * At beta = 1 the shape factor is exactly 1/sin(eps), because
#     sqrt(1 + cot^2 eps) = csc(eps).  So the "air-mass" scaling is not an ad
#     hoc correction: it IS the Kauth & Penquite ellipsoid model at unit cloud
#     aspect ratio, which sits mid-range of the published cumulus interval
#     beta = 0.6-1.5.
#   * ITU-R P.840-8 Eqs. (12)-(13) normatively use the same 1/sin(elevation)
#     slant-path factor for cloud attenuation over 90 deg >= eps >= 5 deg.
#
#   Sweeping beta over 0.5-1.5 moves the key-weighted pass factor by about
#   +/-13 %, whereas ignoring elevation altogether biases it by about +20 % and
#   lands outside the whole beta band — the parameter uncertainty is smaller
#   than the bias it removes, which is what makes the correction defensible
#   rather than optional.
#
# WHY NOT A CLOUD-COVER THRESHOLD
#   Counting hours with cover < 30 % treats a fractional quantity as a binary
#   one: a grid cell 29 % covered is scored fully clear when the model above
#   says 0.71.  Threshold-then-count is the right estimator for a BINARY
#   high-resolution cloud mask (MSG/SEVIRI at 3 km, as used by the optical
#   feeder-link community), not for a ~31 km reanalysis fraction.  The
#   published thresholds are 10 % [Rotherham 2024, on a cloud mask], 25 %
#   [Ehgamberdiev 2000 / Darwish 2023, on ERA5 night hours] and 80 % [Hossain
#   2025, as a station-exclusion filter]; 30 % is attributable to nobody.  The
#   expectation estimator here has no free threshold at all.  The legacy
#   threshold estimator is kept in :func:`threshold_pcflos` for comparison and
#   for the sensitivity sweep the paper should publish.
#
# References (verified; the earlier draft of this module cited Vasylyev et al.
# and Pirandola et al., neither of which contains any cloud/PCFLOS content —
# see .agents/FORMULAS.md §12 for the full audit):
#   Kauth, R. J. & Penquite, J. L., "The probability of clear lines of sight
#       through a cloudy atmosphere", J. Appl. Meteorol. 6, 1005-1017 (1967).
#       The shape-factor PCLoS family; beta = 0.6-1.5 for cumulus.
#   Ma, Y., PhD thesis, Univ. of Maryland (2004), Ch. 3 — open-access
#       derivation of the same family (Eq. 3.28 ellipsoid, 3.27 cylinder).
#   Reinke, D. L. & Vonder Haar, T. H., "Probability of Cloud-Free-Line-of-
#       Sight (PCFLOS) derived from CloudSat and CALIPSO cloud observations",
#       EUMETSAT Meteorological Satellite Conference — nadir identity
#       PCFLOS = 1 - N, and the passive-sensor limitations.
#   Recommendation ITU-R P.840-8 (08/2019), Eqs. (12)-(13) — normative
#       1/sin(elevation) slant-path scaling for cloud attenuation.
#   Lund, I. A. & Shanklin, M. D., J. Appl. Meteorol. 11, 773 (1972) and
#       12, 28 (1973) — observational CFLOS vs sky cover AND elevation angle.
#   Anipeddi, N. L., Horgan, J., Oi, D. K. L. & Kilbane, D., "Optical ground
#       station diversity for satellite QKD in Ireland", EPJ Quantum Technol.
#       (2025), doi:10.1140/epjqt/s40507-025-00390-x, arXiv:2408.08657 — the
#       closest precedent: annual clear-sky key scaled by 1 - <cloud cover>.
#   Hossain, M. Z. et al., arXiv:2512.12514 (2025) — per-slot key
#       (1 - c) * lambda * R, after Polnik et al., EPJ Quantum Technol. 7, 3
#       (2020), the origin of the linear cloud scaling.
#   Sidhu, J. S. et al., npj Quantum Inf. 8, 18 (2022) — finite-key
#       superadditivity ell_M >= M * ell_1 (used for the upper-bound argument
#       in :func:`effective_key_mb`); their annual key explicitly "neglecting
#       weather".
#   Eastman, R. & Warren, S. G., J. Climate 27, 2386 (2014) — diurnal cycles
#       of cloud type: why night-conditioning matters and why its SIGN is
#       regime-dependent.
#   Sanchez Net, M., del Portillo, I., Crawley, E. & Cameron, B., J. Opt.
#       Commun. Netw. 8, 800 (2016) — why an independence product overstates
#       optical-ground-station network diversity.
#   Lyras, N. K., Kourogiorgas, C. I. & Panagopoulos, A. D., IEEE Commun.
#       Lett. 21, 1537 (2017); Proc. SPIE 11180, 111801G (ICSO 2018) — the full
#       3-D ILWC ray-traced CFLOS that this module approximates, and the model
#       Ntanos et al. 2021 itself uses.
#
# Exports:
#   is_night_local_solar(utc_hour, lon_deg) -> bool
#   cflos_shape_factor(elev_deg, beta) -> float
#   pcflos_hour(cover_frac, elev_deg, beta) -> float
#   monthly_cover_stats(hourly, night_only, lon_deg) -> dict
#   pcflos_from_hist(counts, elev_deg, beta) -> float
#   pcflos_table(stats, elev_deg, beta) -> dict
#   availability_factor(month, stats, elev_deg, beta) -> float
#   pcflos_profile(stats, month, beta, step_deg) -> dict
#   pcflos_profile_annual(stats, beta, step_deg) -> dict
#   profile_at(profile, elev_deg) -> float
#   pass_availability(elev_series, weights, profile) -> dict
#   threshold_pcflos(hourly, threshold_pct, night_only, lon_deg) -> dict
#   joint_pcflos(hourly_by_station, ...) -> dict
#   effective_key_mb(key_mb, fk_fraction, availability) -> float
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Cloud aspect ratio beta = h/(2r).  beta = 1 makes the shape factor exactly
# 1/sin(elevation) and sits mid-range of the published cumulus interval
# 0.6-1.5 [Kauth & Penquite 1967].
DEFAULT_CLOUD_ASPECT_RATIO = 1.0

# Legacy threshold estimator only — see the module note above.  Kept because
# routers/relay.py and its tests use it, and because the paper should publish
# the threshold sweep as a sensitivity result.
DEFAULT_THRESHOLD_PCT = 30.0

# Cloud-cover histogram resolution: 101 buckets of 1 % of cover.  ERA5 cover
# arrives as integer percent from the Open-Meteo archive, so this is lossless
# for real data; for float input the rounding is unbiased and shifts PCFLOS by
# well under a percent, far below every other uncertainty here.
COVER_BINS = 101

# Daylight window in local solar time.  This is the SINGLE definition of
# day/night in the project: routers/paper.py:_is_night delegates here, so the
# PCFLOS conditioning and the pass filter can never diverge (a night-only key
# integral weighted by an all-hours cloud statistic is the wrong conditional
# probability).  Note it is a solar-time convention, not astronomical
# darkness — at 55 deg N in June the window still contains civil twilight.
DAY_START_H = 6.0
DAY_END_H = 18.0


# ── Day / night ──────────────────────────────────────────────────────────────

def is_night_local_solar(
    utc_hour: float,
    lon_deg: float,
    *,
    day_start_h: float = DAY_START_H,
    day_end_h: float = DAY_END_H,
) -> bool:
    """Night test from a UTC hour, using local solar time ~ UTC + lon/15."""
    local = (utc_hour + lon_deg / 15.0) % 24.0
    return not (day_start_h <= local < day_end_h)


# ── The shape factor and the single-hour mapping ─────────────────────────────

def cflos_shape_factor(
    elev_deg: float,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> float:
    """Kauth & Penquite (1967) ellipsoid shape factor f(eps).

        f(eps) = sqrt(1 + beta^2 cot^2 eps)

    which is 1 at zenith and 1/sin(eps) when beta = 1.  f grows without bound
    as eps -> 0: a horizontal line of sight traverses unbounded horizontal
    distance through the cloud layer.

    Args:
        elev_deg: Link elevation angle in degrees.  <= 0 has no line of sight.
        beta:     Cloud aspect ratio h/(2r).  0 disables the correction
                  (f == 1, the zenith-only proxy).

    Returns:
        The shape factor, or ``inf`` at or below the horizon.
    """
    if elev_deg is None:
        return float("inf")
    e = float(elev_deg)
    if e <= 0.0:
        return float("inf")
    if e >= 90.0:
        return 1.0
    b = max(0.0, float(beta))
    if b == 0.0:
        return 1.0
    cot = math.cos(math.radians(e)) / math.sin(math.radians(e))
    return math.sqrt(1.0 + b * b * cot * cot)


def pcflos_hour(
    cover_frac: float,
    elev_deg: float = 90.0,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> float:
    """P_CFLOS for ONE hour's cloud fraction at one elevation.

        P = (1 - N) ** f(eps)

    Args:
        cover_frac: Absolute cloud fraction N in [0, 1] (NOT percent).
        elev_deg:   Elevation angle in degrees; 90 gives the exact nadir
                    identity P = 1 - N.
        beta:       Cloud aspect ratio.

    Returns:
        Probability in [0, 1].
    """
    clear = 1.0 - max(0.0, min(1.0, float(cover_frac)))
    if clear <= 0.0:
        return 0.0
    f = cflos_shape_factor(elev_deg, beta)
    if math.isinf(f):
        return 0.0
    if clear >= 1.0:
        return 1.0
    return clear ** f


# ── Monthly statistics from an hourly series ─────────────────────────────────

def monthly_cover_stats(
    hourly: Dict[str, Any],
    *,
    night_only: bool = False,
    lon_deg: float = 0.0,
    bins: int = COVER_BINS,
) -> Dict[str, Any]:
    """Summarise an hourly cloud-cover series into per-month histograms.

    A histogram — not a mean — because P_CFLOS is a CONVEX function of the
    cover, so the expectation of (1-N)^f is not (1-<N>)^f.  Keeping the
    distribution makes the elevation-resolved factor exact and lets any
    elevation be evaluated later in O(bins) without rescanning 8760 hours.

    Args:
        hourly: ``{"time": [ISO strings, UTC], "cloud_cover": [percent|None]}``
            as returned by the Open-Meteo ERA5 archive.
        night_only: Restrict the statistic to nighttime hours.  Use this when
            the link itself is nighttime-only: an all-hours statistic is the
            wrong conditional probability for a night-only link.  The sign of
            the day/night difference is REGIME-dependent, not universal —
            convective cumulus peaks in the afternoon, but boundary-layer
            stratus and fog peak in the early morning, and the diurnal
            amplitude is about 2x larger over land than ocean [Eastman &
            Warren 2014].  So report both and let the site decide.
        lon_deg: Station longitude, for the local-solar-time night test.
        bins: Histogram resolution (default 101 = 1 % of cover per bucket).

    Returns:
        Dict with:
          ``monthly_hist`` {1..12: [bins counts]} — months present in the data
          ``annual_hist``  [bins counts] — pooled
          ``hours``        {1..12: valid-hour count}
          ``valid_hours``  int
          ``mean_cover_monthly`` {1..12: fraction}, ``mean_cover_annual``
          ``night_only``, ``bins`` — echoed for provenance
    """
    nb = max(2, int(bins))
    times = hourly.get("time") or []
    covers = hourly.get("cloud_cover") or []

    monthly_hist: Dict[int, List[int]] = {}
    annual_hist = [0] * nb
    hours: Dict[int, int] = {}
    cover_sum: Dict[int, float] = {}

    for time_str, cc in zip(times, covers):
        if cc is None:
            continue
        if night_only:
            # ISO-8601 "YYYY-MM-DDTHH:MM"; the hour field starts at index 11.
            try:
                utc_hour = float(time_str[11:13])
            except (ValueError, IndexError):
                continue
            if not is_night_local_solar(utc_hour, lon_deg):
                continue
        try:
            month = int(time_str[5:7])
        except (ValueError, IndexError):
            continue
        frac = max(0.0, min(1.0, float(cc) / 100.0))
        idx = int(round(frac * (nb - 1)))
        idx = max(0, min(nb - 1, idx))
        hist = monthly_hist.setdefault(month, [0] * nb)
        hist[idx] += 1
        annual_hist[idx] += 1
        hours[month] = hours.get(month, 0) + 1
        cover_sum[month] = cover_sum.get(month, 0.0) + frac

    valid = sum(hours.values())
    return {
        "monthly_hist": monthly_hist,
        "annual_hist": annual_hist,
        "hours": dict(hours),
        "valid_hours": valid,
        "mean_cover_monthly": {
            m: (cover_sum[m] / n if n > 0 else 0.0) for m, n in hours.items()
        },
        "mean_cover_annual": (
            sum(cover_sum.values()) / valid if valid > 0 else 0.0
        ),
        "night_only": night_only,
        "bins": nb,
    }


def pcflos_from_hist(
    counts: Sequence[float],
    elev_deg: float = 90.0,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> float:
    """PCFLOS = (1/H) * sum_hours (1 - N_h)^f(eps), evaluated on a histogram.

    Args:
        counts: Bin counts over cover in [0, 1]; bin i is cover i/(len-1).
        elev_deg: Elevation angle in degrees.
        beta: Cloud aspect ratio.

    Returns:
        Probability in [0, 1]; 0.0 for an empty histogram.
    """
    n = len(counts)
    if n < 2:
        return 0.0
    total = float(sum(counts))
    if total <= 0.0:
        return 0.0
    f = cflos_shape_factor(elev_deg, beta)
    if math.isinf(f):
        return 0.0
    acc = 0.0
    for i, c in enumerate(counts):
        if not c:
            continue
        clear = 1.0 - i / (n - 1)
        acc += float(c) * (clear ** f if clear > 0.0 else 0.0)
    return max(0.0, min(1.0, acc / total))


def _hist_for_month(
    stats: Dict[str, Any],
    month: Optional[int],
    min_hours: int,
) -> Optional[Sequence[float]]:
    """Monthly histogram if it is backed by enough hours, else the annual one.

    A month with a handful of valid hours is noise, and silently returning it
    would make an annual total depend on a reanalysis gap.

    Returns None when there is nothing usable — including the case that looks
    fine but is not: ``monthly_cover_stats`` always allocates ``annual_hist`` as
    a list of *bins* zeros, which is a non-empty (truthy) list even when no hour
    entered it.  Testing truthiness alone therefore hands back an all-zero
    histogram, whose expectation is 0.0, silently zeroing a key volume — the one
    thing this module promises not to do.  A series that filters down to nothing
    (e.g. ``night_only=True`` over a daytime-only window) hits exactly that.
    """
    monthly = stats.get("monthly_hist") or {}
    hours = stats.get("hours") or {}
    if month is not None:
        # JSON round-trips turn integer keys into strings; accept both.
        for key in (month, str(month)):
            if key in monthly:
                n = hours.get(key, hours.get(str(key), 0))
                if float(n) >= min_hours and sum(monthly[key]) > 0:
                    return monthly[key]
                break
    annual = stats.get("annual_hist")
    if not annual or sum(annual) <= 0:
        return None
    return annual


def pcflos_table(
    stats: Dict[str, Any],
    *,
    elev_deg: float = 90.0,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> Dict[str, Any]:
    """Evaluate :func:`monthly_cover_stats` output at one elevation.

    Returns:
        ``{"monthly": {month: p}, "annual": p, "elev_deg": ..., "beta": ...}``
    """
    monthly_hist = stats.get("monthly_hist") or {}
    return {
        "monthly": {
            int(m): pcflos_from_hist(h, elev_deg, beta)
            for m, h in monthly_hist.items()
        },
        "annual": pcflos_from_hist(
            stats.get("annual_hist") or [], elev_deg, beta
        ),
        "elev_deg": elev_deg,
        "beta": beta,
    }


def availability_factor(
    month: Optional[int],
    stats: Dict[str, Any],
    *,
    elev_deg: float = 90.0,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
    min_hours: int = 24,
) -> float:
    """Availability factor in [0, 1] for a calendar month and elevation.

    Args:
        month: Calendar month 1-12, or None to request the annual figure.
        stats: Output of :func:`monthly_cover_stats`.
        elev_deg: Elevation angle in degrees.
        beta: Cloud aspect ratio.
        min_hours: Minimum valid hours for a monthly figure to be trusted;
            below it the annual figure is used instead.

    Returns:
        The factor, clamped to [0, 1].  1.0 when there are no statistics at
        all — missing data must never silently zero a key volume; the caller
        decides what to do, and the routers attach an explicit note.
    """
    if not stats:
        return 1.0
    hist = _hist_for_month(stats, month, min_hours)
    if not hist:
        return 1.0
    return pcflos_from_hist(hist, elev_deg, beta)


# ── PCFLOS as a function of elevation ────────────────────────────────────────

# Mean days per calendar month over a Julian year (sums to 365.25), used to
# weight monthly statistics into an annual figure.  A pass geometry recurs all
# year round, so an annual expectation must average the cloud statistic over
# the calendar, not use the month the simulation window happens to sit in.
MONTH_DAYS = (31.0, 28.25, 31.0, 30.0, 31.0, 30.0,
              31.0, 31.0, 30.0, 31.0, 30.0, 31.0)

# Elevation grid step for the P_CFLOS(eps) profile.  0.5 deg over 0-90 is 181
# histogram evaluations built once per station, after which a per-sample lookup
# is a linear interpolation instead of a 101-bin sum.
DEFAULT_PROFILE_STEP_DEG = 0.5


def pcflos_profile(
    stats: Dict[str, Any],
    *,
    month: Optional[int] = None,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
    min_hours: int = 24,
    step_deg: float = DEFAULT_PROFILE_STEP_DEG,
) -> Dict[str, Any]:
    """Tabulate P_CFLOS against elevation for one month (or the annual pool).

    This is both the fast path for per-pass reduction and a reportable object
    in its own right: P_CFLOS versus elevation IS the figure that shows how much
    availability a low-elevation pass loses.

    Args:
        stats: Output of :func:`monthly_cover_stats`.
        month: Calendar month 1-12, or None for the annual pool.  A month with
            fewer than *min_hours* valid hours falls back to the annual pool.
        beta: Cloud aspect ratio.
        min_hours: Minimum valid hours for a monthly histogram to be trusted.
        step_deg: Elevation grid step in degrees.

    Returns:
        ``{"p": [values on 0..90 deg], "step_deg", "beta", "month", "zenith",
        "resolved"}`` where ``resolved`` is False when no statistics were
        available (in which case ``p`` is all ones — missing data must never
        silently zero a key volume).
    """
    step = max(0.05, float(step_deg))
    n_grid = int(round(90.0 / step)) + 1
    hist = _hist_for_month(stats, month, min_hours) if stats else None
    if not hist:
        return {"p": [1.0] * n_grid, "step_deg": step, "beta": beta,
                "month": month, "zenith": 1.0, "resolved": False}
    p = [pcflos_from_hist(hist, i * step, beta) for i in range(n_grid)]
    return {"p": p, "step_deg": step, "beta": beta, "month": month,
            "zenith": p[-1], "resolved": True}


def pcflos_profile_annual(
    stats: Dict[str, Any],
    *,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
    min_hours: int = 24,
    step_deg: float = DEFAULT_PROFILE_STEP_DEG,
) -> Dict[str, Any]:
    """Day-weighted mean of the 12 monthly profiles: sum_m w_m P_m(eps).

    Use this for a result that is scaled to a year from a short simulation
    window.  Multiplying by the single month the window falls in would
    extrapolate (say) March cloud statistics to all twelve months; averaging
    over the calendar with day weights is the expectation over a year of
    recurring passes.  Reduces exactly to the monthly profile when all months
    share one histogram.
    """
    step = max(0.05, float(step_deg))
    n_grid = int(round(90.0 / step)) + 1
    if not stats:
        return {"p": [1.0] * n_grid, "step_deg": step, "beta": beta,
                "month": None, "zenith": 1.0, "resolved": False,
                "monthly_zenith": {}}
    acc = [0.0] * n_grid
    w_total = 0.0
    monthly_zenith: Dict[int, float] = {}
    resolved = False
    for m in range(1, 13):
        prof = pcflos_profile(stats, month=m, beta=beta, min_hours=min_hours,
                              step_deg=step)
        w = MONTH_DAYS[m - 1]
        resolved = resolved or prof["resolved"]
        monthly_zenith[m] = prof["zenith"]
        for i in range(n_grid):
            acc[i] += w * prof["p"][i]
        w_total += w
    p = [v / w_total for v in acc] if w_total > 0 else [1.0] * n_grid
    return {"p": p, "step_deg": step, "beta": beta, "month": None,
            "zenith": p[-1], "resolved": resolved,
            "monthly_zenith": monthly_zenith}


def profile_at(profile: Dict[str, Any], elev_deg: Optional[float]) -> float:
    """Interpolate a :func:`pcflos_profile` at one elevation."""
    p = profile.get("p") or []
    if not p:
        return 1.0
    if elev_deg is None:
        return 0.0
    e = float(elev_deg)
    if e <= 0.0:
        return 0.0            # no line of sight at or below the horizon
    step = float(profile.get("step_deg") or DEFAULT_PROFILE_STEP_DEG)
    if e >= (len(p) - 1) * step:
        return p[-1]
    pos = e / step
    lo = int(pos)
    frac = pos - lo
    return p[lo] * (1.0 - frac) + p[lo + 1] * frac


# ── Per-pass reduction ───────────────────────────────────────────────────────

def pass_availability(
    elev_deg: Sequence[Optional[float]],
    weights: Sequence[float],
    profile: Dict[str, Any],
    *,
    dt_s: Optional[Sequence[float]] = None,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> Dict[str, float]:
    """Reduce one pass's elevation profile to availability scalars.

    A pass sweeps elevation, so there is no single P_CFLOS for it.  Three
    reductions, and the paper needs more than one of them:

    * ``keyWeighted`` — sum_t P(eps_t) k_t / sum_t k_t, with k_t the
      instantaneous key rate.  This is the factor to multiply a pass key
      volume by, because it weights availability by where the key actually
      comes from.  It is also the factor that makes the expectation identity
      correct: p must sit INSIDE the pass sum, since high-elevation passes are
      both more likely to be clear and more productive, and factoring a scalar
      mean out of the sum drops a positive covariance and under-counts key.
    * ``timeWeighted`` — the same average over time instead of key.  This is
      the link-availability / duty-cycle figure, and it is roughly twice as
      sensitive to the elevation correction as the key-weighted one, so the two
      must never be used interchangeably.
    * ``zenith`` — the elevation-independent proxy, kept so the bias being
      removed stays reportable instead of invisible.

    ``minElev`` is P_CFLOS at the lowest key-producing elevation: the
    conservative figure for "clear over the whole pass", as opposed to the
    key-weighted mean clear fraction.

    Args:
        elev_deg: Per-sample elevation over the pass window (None allowed).
        weights: Per-sample key rate (any consistent unit); may be all zero.
        profile: Output of :func:`pcflos_profile` / :func:`pcflos_profile_annual`.
        dt_s: Optional per-sample time weights; defaults to uniform.
        beta: Cloud aspect ratio, for the reported mean shape factor only.

    Returns:
        ``{"keyWeighted", "timeWeighted", "zenith", "minElev", "shapeFactor"}``
        where ``shapeFactor`` is the key-weighted mean f(eps) — one number
        summarising how much slant path this pass actually sees.
    """
    if not profile or not profile.get("resolved", False):
        return {"keyWeighted": 1.0, "timeWeighted": 1.0, "zenith": 1.0,
                "minElev": 1.0, "shapeFactor": 1.0}

    p_zenith = float(profile.get("zenith") or 1.0)

    w_key_sum = 0.0
    w_time_sum = 0.0
    acc_key = 0.0
    acc_time = 0.0
    acc_f = 0.0
    lowest: Optional[float] = None

    for i in range(len(elev_deg)):
        e = elev_deg[i]
        if e is None:
            continue
        e = float(e)
        if e <= 0.0:
            continue
        dt = float(dt_s[i]) if dt_s is not None and i < len(dt_s) else 1.0
        k = max(0.0, float(weights[i]) if i < len(weights) else 0.0) * dt
        p = profile_at(profile, e)
        acc_time += p * dt
        w_time_sum += dt
        if k > 0.0:
            acc_key += p * k
            acc_f += cflos_shape_factor(e, beta) * k
            w_key_sum += k
            # Lowest elevation that actually produces key — the relevant
            # geometry for an all-or-nothing "clear for the whole session".
            if lowest is None or e < lowest:
                lowest = e

    p_time = (acc_time / w_time_sum) if w_time_sum > 0.0 else p_zenith
    # No key anywhere in the window: fall back to the time-weighted figure
    # rather than inventing a key-weighted one from a zero denominator.
    p_key = (acc_key / w_key_sum) if w_key_sum > 0.0 else p_time
    f_key = (acc_f / w_key_sum) if w_key_sum > 0.0 else 1.0
    p_min = profile_at(profile, lowest) if lowest is not None else p_time

    return {
        "keyWeighted": p_key,
        "timeWeighted": p_time,
        "zenith": p_zenith,
        "minElev": p_min,
        "shapeFactor": f_key,
    }


# ── Legacy threshold estimator (comparison / sensitivity sweep) ──────────────

def threshold_pcflos(
    hourly: Dict[str, Any],
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    *,
    night_only: bool = False,
    lon_deg: float = 0.0,
) -> Dict[str, Any]:
    """PCFLOS as P(cover < threshold) — the count estimator, for comparison.

    This is a DIFFERENT quantity from :func:`pcflos_from_hist` at zenith and
    is generally larger.  It is the correct estimator for a binary
    high-resolution cloud mask and the wrong one for a ~31 km reanalysis
    fraction (see the module header).  Kept because routers/relay.py uses it
    and because the threshold sweep 10/20/30/50 % is a sensitivity result the
    paper should publish rather than a choice it should hide.

    Returns:
        ``{"monthly", "annual", "hours", "valid_hours", "night_only",
        "threshold_pct"}``.
    """
    times = hourly.get("time") or []
    covers = hourly.get("cloud_cover") or []

    clear: Dict[int, int] = {}
    total: Dict[int, int] = {}

    for time_str, cc in zip(times, covers):
        if cc is None:
            continue
        if night_only:
            try:
                utc_hour = float(time_str[11:13])
            except (ValueError, IndexError):
                continue
            if not is_night_local_solar(utc_hour, lon_deg):
                continue
        try:
            month = int(time_str[5:7])
        except (ValueError, IndexError):
            continue
        total[month] = total.get(month, 0) + 1
        if cc < threshold_pct:
            clear[month] = clear.get(month, 0) + 1

    valid = sum(total.values())
    return {
        "monthly": {m: (clear.get(m, 0) / n if n > 0 else 0.0)
                    for m, n in total.items()},
        "annual": (sum(clear.values()) / valid) if valid > 0 else 0.0,
        "hours": dict(total),
        "valid_hours": valid,
        "night_only": night_only,
        "threshold_pct": threshold_pct,
    }


# ── Multi-station (OGS network) availability ─────────────────────────────────

def joint_pcflos(
    hourly_by_station: Dict[str, Dict[str, Any]],
    *,
    night_only: bool = False,
    lon_by_station: Optional[Dict[str, float]] = None,
    elev_by_station: Optional[Dict[str, float]] = None,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
) -> Dict[str, Any]:
    """Network availability from ALIGNED hourly series — no independence assumption.

    Hour by hour on the shared time grid,

        P_any(h) = 1 - prod_i (1 - p_i(h)),    p_i(h) = (1 - N_i(h))^f(eps_i)

    and the reported ``annual``/``monthly`` are the means of P_any over hours.
    This uses the REAL joint distribution of the cloud fractions N_i, so the
    synoptic correlation between sites is measured rather than assumed.  What
    remains assumed is only that, GIVEN the local cloud fractions, one site's
    particular line of sight is blocked independently of another's — which is
    reasonable for cells hundreds of km apart and is far weaker than assuming
    the fractions themselves are independent.

    ``annual_independent`` / ``monthly_independent`` apply that stronger, wrong
    assumption (``1 - prod(1 - <p_i>)``) because the GAP between the two is the
    result: synoptic cloud fields are correlated over hundreds of km, so an
    independence assumption overstates the diversity gain of a regional network
    [Sanchez Net et al. 2016].  ``cross_correlation`` reports the measured
    Pearson correlation of the hourly cover series for every station pair —
    anti-correlated sites are what makes a small network work at all [Anipeddi
    et al. 2025 found -0.76 within Ireland].

    All stations must come from the same request window so their ``time``
    arrays align; alignment is by timestamp, not by index, so a missing hour at
    one site cannot silently shift another site's series.

    Args:
        hourly_by_station: ``{station_id: hourly_dict}``.
        night_only: Restrict to nighttime hours (per-station local solar time).
        lon_by_station: ``{station_id: longitude}``, required when *night_only*.
        elev_by_station: ``{station_id: elevation_deg}`` at which to evaluate
            each site; defaults to zenith (90 deg).
        beta: Cloud aspect ratio.

    Returns:
        ``monthly`` / ``annual`` (measured joint), ``monthly_independent`` /
        ``annual_independent``, ``marginals`` {station: annual p_i},
        ``cross_correlation`` {"a|b": r}, ``hours``, ``valid_hours``,
        ``n_stations``, ``night_only``, ``beta``.
    """
    lons = lon_by_station or {}
    elevs = elev_by_station or {}
    ids = sorted(hourly_by_station.keys())
    if not ids:
        return {
            "monthly": {}, "annual": 0.0, "monthly_independent": {},
            "annual_independent": 0.0, "marginals": {},
            "cross_correlation": {}, "hours": {}, "valid_hours": 0,
            "n_stations": 0, "night_only": night_only, "beta": beta,
        }

    # p_by_time[station][timestamp] = P_CFLOS for that hour.  None samples are
    # absent, so a station with a data gap simply does not vote for that hour.
    p_by_time: Dict[str, Dict[str, float]] = {}
    cover_by_time: Dict[str, Dict[str, float]] = {}
    for sid in ids:
        h = hourly_by_station[sid] or {}
        lon = float(lons.get(sid, 0.0))
        elev = float(elevs.get(sid, 90.0))
        per: Dict[str, float] = {}
        cov: Dict[str, float] = {}
        for time_str, cc in zip(h.get("time") or [], h.get("cloud_cover") or []):
            if cc is None:
                continue
            if night_only:
                try:
                    if not is_night_local_solar(float(time_str[11:13]), lon):
                        continue
                except (ValueError, IndexError):
                    continue
            frac = max(0.0, min(1.0, float(cc) / 100.0))
            cov[time_str] = frac
            per[time_str] = pcflos_hour(frac, elev, beta)
        p_by_time[sid] = per
        cover_by_time[sid] = cov

    # Only hours where EVERY station reported can be used for a joint
    # statistic; mixing partial coverage would bias P(any clear) upward.
    common: Optional[set] = None
    for sid in ids:
        keys = set(p_by_time[sid].keys())
        common = keys if common is None else (common & keys)
    common_sorted = sorted(common or set())

    any_clear: Dict[int, float] = {}
    total: Dict[int, int] = {}
    per_station_sum: Dict[str, float] = {sid: 0.0 for sid in ids}
    per_station_month: Dict[str, Dict[int, float]] = {sid: {} for sid in ids}
    for time_str in common_sorted:
        try:
            month = int(time_str[5:7])
        except (ValueError, IndexError):
            continue
        total[month] = total.get(month, 0) + 1
        blocked = 1.0
        for sid in ids:
            p = p_by_time[sid][time_str]
            per_station_sum[sid] += p
            pm = per_station_month[sid]
            pm[month] = pm.get(month, 0.0) + p
            blocked *= (1.0 - p)
        any_clear[month] = any_clear.get(month, 0.0) + (1.0 - blocked)

    n_common = len(common_sorted)
    monthly = {m: (any_clear.get(m, 0.0) / n if n > 0 else 0.0)
               for m, n in total.items()}
    annual = (sum(any_clear.values()) / n_common) if n_common > 0 else 0.0

    marginals = {
        sid: (per_station_sum[sid] / n_common if n_common > 0 else 0.0)
        for sid in ids
    }

    # What the same marginals would give if the cloud FIELDS were independent.
    monthly_indep: Dict[int, float] = {}
    for m, n in total.items():
        if n <= 0:
            monthly_indep[m] = 0.0
            continue
        prod = 1.0
        for sid in ids:
            prod *= (1.0 - per_station_month[sid].get(m, 0.0) / n)
        monthly_indep[m] = 1.0 - prod

    prod_annual = 1.0
    for sid in ids:
        prod_annual *= (1.0 - marginals[sid])

    return {
        "monthly": monthly,
        "annual": annual,
        "monthly_independent": monthly_indep,
        "annual_independent": 1.0 - prod_annual,
        "marginals": marginals,
        "cross_correlation": _cross_correlations(cover_by_time, common_sorted),
        "hours": dict(total),
        "valid_hours": n_common,
        "n_stations": len(ids),
        "night_only": night_only,
        "beta": beta,
    }


def _cross_correlations(
    series_by_station: Dict[str, Dict[str, float]],
    common: Sequence[str],
) -> Dict[str, float]:
    """Pearson correlation of hourly cloud cover for every station pair."""
    ids = sorted(series_by_station.keys())
    n = len(common)
    if n < 2 or len(ids) < 2:
        return {}
    out: Dict[str, float] = {}
    vecs = {sid: [series_by_station[sid][t] for t in common] for sid in ids}
    means = {sid: sum(v) / n for sid, v in vecs.items()}
    devs = {sid: [x - means[sid] for x in vecs[sid]] for sid in ids}
    norms = {sid: math.sqrt(sum(d * d for d in devs[sid])) for sid in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            denom = norms[a] * norms[b]
            if denom <= 0.0:
                continue  # a constant series has no correlation to report
            cov = sum(da * db for da, db in zip(devs[a], devs[b]))
            out[f"{a}|{b}"] = cov / denom
    return out


# ── Composition into a key volume ───────────────────────────────────────────

def effective_key_mb(
    key_mb: float,
    fk_fraction: Optional[float] = None,
    availability: Optional[float] = None,
) -> float:
    """Compose the clear-sky asymptotic key volume into an expected one.

        expected = key_mb x fk_fraction x availability

    The three factors are deliberately separate quantities and must be
    multiplied exactly once each:

    * ``key_mb``      — asymptotic, clear-sky, cloud-free pass integral
    * ``fk_fraction`` — finite-size penalty for the pass block (Lim et al. 2014)
    * ``availability``— probability the pass happens under a cloud-free line of
      sight, key-weighted over the pass elevation profile

    WHY THIS IS AN UPPER BOUND, NOT AN APPROXIMATION.  With ``availability``
    read as the mean clear FRACTION of the pass, the product is a rigorous
    upper bound on the cloud-averaged key.  The finite-key length is
    superadditive — ell(n)/n is non-decreasing and ell(0) = 0, so ell lies
    below the chord from the origin — hence for a usable fraction f

        ell(f n) <= f ell(n),      and  E[ell(n(f))] <= E[f] ell(n).

    Equality holds if and only if f is supported on {0, 1}, i.e. exactly the
    all-or-nothing case.  Superadditivity is published, not assumed: Sidhu et
    al. (npj Quantum Inf. 8, 18 (2022)) state ell_M >= M ell_1 for M passes.
    Stating an upper bound is much stronger than claiming an approximation,
    and the all-or-nothing reading is itself exact under the operational
    assumption that a session is only started when the sky is clear at pass
    start (a go/no-go decision from a forecast or an all-sky camera).
    """
    out = max(0.0, float(key_mb))
    if fk_fraction is not None:
        out *= max(0.0, min(1.0, float(fk_fraction)))
    if availability is not None:
        out *= max(0.0, min(1.0, float(availability)))
    return out


# ---------------------------------------------------------------------------
# LIMITATIONS — state these in the paper, do not let them be discovered
# ---------------------------------------------------------------------------
# 1. ALL-OR-NOTHING PASSES.  See :func:`effective_key_mb`.  Cloud arriving
#    partway through a pass shrinks the finite-key block, and because ell is
#    threshold-like the true expectation is then BELOW p x ell(n) — exactly
#    zero once the surviving block falls under n_min.  In relative terms the
#    effect is unbounded (it decides whether a marginal pass yields any key at
#    all); in absolute terms the annual total is dominated by good passes where
#    the shortfall is a few percent.  Say both.  Intra-pass cloud onset is not
#    modelled, and cannot be calibrated: the available cloud products are
#    hourly (ERA5, Visual Crossing) while a LEO pass is 200-440 s.
# 2. AREAL FRACTION AS A LINE-OF-SIGHT PROXY.  ERA5 total cloud cover is a
#    ~31 km grid-box mean produced under a maximum-random overlap assumption —
#    a model diagnostic, not an observed line of sight.  Sub-grid gaps a real
#    OGS could exploit are invisible, and optically thin cirrus that still
#    ruins a single-photon link is under-weighted.  Because (1-N)^f is convex
#    in N, averaging cover over the cell before exponentiating biases PCFLOS
#    LOW relative to a point-resolved calculation (Jensen); direction known,
#    magnitude not, without a cloud mask.
# 3. HORIZONTAL PARALLAX — the honest limit of the air-mass approach.  At 20
#    deg elevation the line of sight leaves a 6 km cloud layer 16.5 km from the
#    station, and a 10 km layer 33 km away, i.e. up to a full ERA5 cell.  The
#    cloud fraction used is not the one the ray actually traverses.  Cloud-mask
#    reprojection or the Lyras 3-D ILWC ray tracing is the fix, and is out of
#    scope here.
# 4. STATION ALTITUDE IS UNMODELLED.  Grid-box cover counts cloud BELOW an
#    elevated OGS.  Helmos at 2.34 km sits above much of the low cloud deck, so
#    total cover overstates blockage there while a sea-level site is scored
#    correctly.  Willitsford et al., J. Appl. Remote Sens. 16, 028502 (2022) is
#    the reference method; ERA5 exposes lcc/mcc/hcc so only layers above the
#    station need counting.  Not done here.
# 5. EARTH CURVATURE is NOT a limitation: the flat 1/sin(eps) slant factor is
#    within 0.35 % of the exact spherical geometry at 20 deg elevation for a
#    6 km cloud top, so no correction is justified above ~15 deg.
# 6. INDEPENDENCE BETWEEN SITES.  Combining per-site factors as
#    1 - prod(1 - p_i) assumes site-to-site cloud independence and overstates a
#    regional network's diversity gain.  Use :func:`joint_pcflos`, which
#    measures the joint statistic on the aligned hourly grid and reports the
#    independence figure and the measured cross-correlations alongside it.
# 7. A MEAN FACTOR IS NOT AN AVAILABILITY PERCENTILE.  The optical-comms
#    ground-station-network literature reports availability against targets
#    like 99.9 %, not mean multipliers.  A scalar mean discards the
#    interannual variance, the worst-month figure and the 5th/95th-percentile
#    annual key.
# 8. NOT COMPARABLE TO NTANOS ET AL. 2021 TABLE 1, which is explicitly
#    cloud-free ("no link interruption due to clouds").  Keep the clear-sky and
#    cloud-weighted totals as separate reported columns so the two error
#    sources are never confounded.
# ---------------------------------------------------------------------------
