# ---------------------------------------------------------------------------
# app/services/pcflos_svc.py
# ---------------------------------------------------------------------------
# Purpose : PCFLOS — Probability of Cloud-Free Line of Sight.
#
#           Fetches 1 year of hourly cloud_cover from the Open-Meteo ERA5
#           reanalysis archive and reduces it to monthly / annual PCFLOS.
#           This module owns the NETWORK and the CACHE; all the physics lives
#           in physics/availability.py, which is pure by design.
#
#           Two estimators, and the difference matters:
#             * "expectation" (default) — PCFLOS = mean over hours of
#               (1 − N_h)^f(ε), i.e. the Kauth & Penquite (1967) shape-factor
#               model averaged over the real hourly cover distribution.  No
#               free threshold; reduces to 1 − <N> at zenith, which is both the
#               exact nadir identity and the definition used by the published
#               satellite-QKD precedents (Anipeddi et al. 2025; Hossain et al.
#               2025).
#             * "threshold" — the legacy P(cover < threshold) count.  Correct
#               for a BINARY high-resolution cloud mask, a category error on a
#               ~31 km reanalysis fraction (it scores a 29 %-covered cell as
#               fully clear).  Kept for routers/relay.py and for the threshold
#               sensitivity sweep the paper should publish.
#
# References: see physics/availability.py for the full, verified list.  Two
#   citations previously carried here were WRONG and have been removed:
#   Phys. Rev. A 96, 043856 (2017) is "Free-space quantum links under diverse
#   weather conditions" (rain and haze; no cloud/CFLOS content whatsoever), and
#   Pirandola et al., Adv. Opt. Photon. 12, 1012 (2020) contains no cloud
#   availability material at all.  The 30 % threshold was attributed to the
#   former; it is attributable to nobody.  Verified published thresholds are
#   10 % [Rotherham et al., arXiv:2410.23470, on a 3 km cloud mask], 25 %
#   [Ehgamberdiev et al., A&AS 145, 293 (2000); Darwish et al., arXiv:2310.04746,
#   on ERA5 night hours] and 80 % [Hossain et al., arXiv:2512.12514, as a
#   station-exclusion filter].
#
# Exports:
#   compute_pcflos_monthly(hourly, threshold_pct) -> dict[int, float]
#   compute_pcflos(lat, lon, year, threshold_pct, ...) -> dict
#   fetch_hourly_cover(lat, lon, year) -> dict
#   set_disk_cache(enabled, directory=None) / disk_cache_dir() -> Path | None
#   PCFLOSError
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..config import OPEN_METEO_ARCHIVE_URL
from ..physics.availability import (
    DEFAULT_CLOUD_ASPECT_RATIO,
    monthly_cover_stats,
    pcflos_table,
    threshold_pcflos,
)

logger = logging.getLogger(__name__)


class PCFLOSError(RuntimeError):
    """Raised when cloud cover data cannot be fetched from the archive API."""


# ── Persistent (on-disk) archive cache ───────────────────────────────────────
# The in-process ``lru_cache`` below dies with the process, so every paper /
# sensitivity run re-downloaded 8760 samples per station and produced numbers
# that depended on whatever Open-Meteo served that day.  A reanalysis year is
# immutable, so it is cached to disk: reruns are then byte-identical and
# offline, which is what makes a published sensitivity sweep reproducible.
#
# Layout: <root>/.cache/era5/cover_<lat>_<lon>_<year>.json  (gitignored)
# Override with $SIMULCTTC_ERA5_CACHE; disable with set_disk_cache(False).

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "era5"
_disk_cache_dir: Optional[Path] = Path(
    os.environ.get("SIMULCTTC_ERA5_CACHE") or _DEFAULT_CACHE_DIR
)


def set_disk_cache(enabled: bool, directory: Optional[str] = None) -> None:
    """Enable/disable (or relocate) the on-disk ERA5 archive cache.

    Tests use this to guarantee a run touches neither the network nor a
    developer's cache; study scripts use it to pin a specific cache directory.
    """
    global _disk_cache_dir
    if not enabled:
        _disk_cache_dir = None
    else:
        _disk_cache_dir = Path(directory) if directory else Path(
            os.environ.get("SIMULCTTC_ERA5_CACHE") or _DEFAULT_CACHE_DIR
        )
    _archive_cached.cache_clear()


def disk_cache_dir() -> Optional[Path]:
    """Return the active on-disk cache directory (None when disabled)."""
    return _disk_cache_dir


def _cache_file(lat: float, lon: float, year: int) -> Optional[Path]:
    if _disk_cache_dir is None:
        return None
    # Fixed-width signed keys so the filename sorts and never collides with a
    # differently-formatted representation of the same coordinate.
    return _disk_cache_dir / f"cover_{lat:+08.3f}_{lon:+08.3f}_{int(year)}.json"


def _disk_read(lat: float, lon: float, year: int) -> Optional[dict]:
    path = _cache_file(lat, lon, year)
    if path is None or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        logger.warning("ERA5 disk cache unreadable, ignoring: %s", path, exc_info=True)
        return None
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    # A truncated or empty cache entry must fall through to a refetch rather
    # than poison every downstream statistic with a silent empty series.
    if not isinstance(hourly, dict) or not hourly.get("time"):
        logger.warning("ERA5 disk cache entry incomplete, ignoring: %s", path)
        return None
    return hourly


def _disk_write(lat: float, lon: float, year: int, hourly: dict) -> None:
    path = _cache_file(lat, lon, year)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a crash mid-write must not leave a half file that the
        # next run would read as a valid (short) year.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({
                    "source": "open-meteo ERA5 archive",
                    "lat": lat, "lon": lon, "year": int(year),
                    "hourly": hourly,
                }, fh)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        # A read-only or full filesystem must degrade to "no cache", never to a
        # failed simulation.
        logger.warning("ERA5 disk cache write failed: %s", path, exc_info=True)


# ── Internal cached fetch ────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _archive_cached(lat: float, lon: float, year: int) -> dict:
    """Fetch 1 year of hourly cloud_cover from Open-Meteo ERA5 archive.

    Results are cached in-process per (lat, lon, year) and, unless disabled via
    :func:`set_disk_cache`, persisted to disk so repeat runs are offline and
    byte-reproducible.

    Args:
        lat:  Latitude (rounded to 3 decimal places for cache key stability).
        lon:  Longitude (rounded to 3 decimal places for cache key stability).
        year: Calendar year (e.g. 2024).

    Returns:
        The ``hourly`` sub-dict from the Open-Meteo archive JSON response,
        containing ``time`` (list of ISO strings) and ``cloud_cover`` (list
        of float | None values in percent).

    Raises:
        PCFLOSError: If the HTTP request fails, returns a non-2xx status, or
            answers 200 with a body that has no ``hourly`` block — the last of
            those used to escape as a bare KeyError and surface as a 500.
    """
    cached = _disk_read(lat, lon, year)
    if cached is not None:
        logger.info(
            "Cloud cover archive served from disk cache: lat=%.3f lon=%.3f year=%d",
            lat, lon, year,
        )
        return cached

    url = OPEN_METEO_ARCHIVE_URL
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": f"{year}-01-01",
        "end_date":   f"{year}-12-31",
        "hourly":     "cloud_cover",
        "timezone":   "UTC",
    }
    logger.info(
        "Fetching cloud cover archive: lat=%.3f lon=%.3f year=%d",
        lat, lon, year,
    )
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        logger.warning("PCFLOS archive fetch failed: %s", exc)
        raise PCFLOSError(str(exc)) from exc
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not hourly or not hourly.get("time"):
        raise PCFLOSError(
            f"archive response for lat={lat} lon={lon} year={year} carries no "
            "hourly cloud_cover block"
        )
    _disk_write(lat, lon, year, hourly)
    return hourly


def fetch_hourly_cover(lat: float, lon: float, year: int) -> dict:
    """Public, cached accessor for the raw hourly cover series.

    Callers that need night-conditioning, elevation resolution or multi-station
    joint statistics need the SERIES, not a reduced monthly table — those are
    all impossible downstream of :func:`compute_pcflos`, which discards it.

    Raises:
        PCFLOSError: On any fetch or payload failure.
    """
    return _archive_cached(round(lat, 3), round(lon, 3), int(year))


# ── Public functions ─────────────────────────────────────────────────────────

def compute_pcflos_monthly(
    hourly: dict,
    threshold_pct: float = 30.0,
) -> dict[int, float]:
    """Monthly PCFLOS by the THRESHOLD estimator: P(cover < threshold_pct).

    Thin wrapper over ``physics.availability.threshold_pcflos`` so the estimator
    exists in exactly one place.  None values in cloud_cover are skipped, from
    both numerator and denominator.

    Args:
        hourly:        Dict with ``time`` (list[str]) and ``cloud_cover``
                       (list[float | None]) as returned by the Open-Meteo
                       archive API.
        threshold_pct: Cloud cover threshold in percent (0–100).  Hours with
                       cloud_cover strictly below this value count as
                       "cloud-free".  The 30 % default is a repo convention and
                       nothing more: it is NOT attributable to any publication
                       (the module header lists the three thresholds that are).
                       Sweep it — 10 / 20 / 30 / 50 % — and publish the
                       sensitivity rather than defending one number.

    Returns:
        Dict mapping month integer (1–12) to PCFLOS fraction (0.0–1.0).
        Only months that appear in the data are included.
    """
    return threshold_pcflos(hourly, threshold_pct)["monthly"]


def compute_pcflos(
    lat: float,
    lon: float,
    year: int,
    threshold_pct: float = 30.0,
    *,
    estimator: str = "expectation",
    elev_deg: float = 90.0,
    beta: float = DEFAULT_CLOUD_ASPECT_RATIO,
    night_only: bool = False,
) -> dict:
    """Compute monthly and annual PCFLOS for a location.

    Fetches 1 year of hourly ERA5 cloud_cover from the Open-Meteo archive, then
    reduces it with BOTH estimators so the two are always comparable — the
    selected one is mirrored into ``monthly_pcflos`` / ``annual_pcflos`` for
    downstream consumers, and the other is reported alongside it.

    Args:
        lat:           Ground station latitude (degrees).
        lon:           Ground station longitude (degrees).
        year:          Calendar year (e.g. 2024) for retrospective data.
        threshold_pct: Cloud cover threshold (%) for the ``threshold``
                       estimator only.
        estimator:     ``"expectation"`` (default) or ``"threshold"``.
        elev_deg:      Elevation at which to evaluate the expectation
                       estimator.  90 (zenith) reduces it to 1 − <N>.
        beta:          Cloud aspect ratio for the shape factor.
        night_only:    Restrict the statistic to night hours (local solar time).

    Returns:
        Dict with ``monthly_pcflos`` / ``annual_pcflos`` (the SELECTED
        estimator), ``monthly_expectation`` / ``annual_expectation``,
        ``monthly_threshold`` / ``annual_threshold``, ``hours`` per month and
        ``valid_hours`` (so a caller can refuse a thin month — the old return
        shape made that impossible), ``mean_cover_monthly`` /
        ``mean_cover_annual``, and the echoed ``year``, ``threshold_pct``,
        ``estimator``, ``elev_deg``, ``beta``, ``night_only``.

    Raises:
        PCFLOSError: If the archive fetch fails.
    """
    hourly = fetch_hourly_cover(lat, lon, year)
    stats = monthly_cover_stats(hourly, night_only=night_only, lon_deg=lon)
    expectation = pcflos_table(stats, elev_deg=elev_deg, beta=beta)
    thresholded = threshold_pcflos(
        hourly, threshold_pct, night_only=night_only, lon_deg=lon)

    selected = thresholded if estimator == "threshold" else expectation

    return {
        "monthly_pcflos":       selected["monthly"],
        "annual_pcflos":        selected["annual"],
        "monthly_expectation":  expectation["monthly"],
        "annual_expectation":   expectation["annual"],
        "monthly_threshold":    thresholded["monthly"],
        "annual_threshold":     thresholded["annual"],
        "hours":                stats["hours"],
        "valid_hours":          stats["valid_hours"],
        "mean_cover_monthly":   stats["mean_cover_monthly"],
        "mean_cover_annual":    stats["mean_cover_annual"],
        "year":                 year,
        "threshold_pct":        threshold_pct,
        "estimator":            estimator,
        "elev_deg":             elev_deg,
        "beta":                 beta,
        "night_only":           night_only,
    }
