# ---------------------------------------------------------------------------
# app/services/tle_service.py
# ---------------------------------------------------------------------------
# Purpose : Fetch and cache Two-Line Element (TLE) datasets from CelesTrak
#           for well-known satellite constellations.
#
# Classes:
#   TleService            – caching TLE downloader
#   TleGroupNotFoundError – unknown constellation alias
#   TleProviderError      – upstream HTTP / parse error
#
# Usage:
#   svc = TleService()
#   data = svc.get_group("starlink")   # returns dict with 'tles' list
# ---------------------------------------------------------------------------
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests


class TleServiceError(RuntimeError):
    pass

class TleGroupNotFoundError(TleServiceError):
    pass

class TleProviderError(TleServiceError):
    pass


@dataclass
class _CacheEntry:
    expires_at: datetime
    payload: Dict[str, Any]


class TleService:
    """Fetches and caches TLE datasets from CelesTrak."""

    ENDPOINT = "https://celestrak.org/NORAD/elements/gp.php"
    GROUP_ALIAS: Dict[str, str] = {
        "starlink": "starlink",
        "oneweb": "oneweb",
        "gps": "gps-ops",
        "galileo": "galileo",
        "glonass": "glonass",
    }

    def __init__(self, ttl: timedelta = timedelta(minutes=30)) -> None:
        self._cache: Dict[str, _CacheEntry] = {}
        self._ttl = ttl

    def list_groups(self) -> List[str]:
        return list(self.GROUP_ALIAS.keys())

    def get_group(self, group_id: str) -> Dict[str, Any]:
        norm = (group_id or "").strip().lower()
        if norm not in self.GROUP_ALIAS:
            raise TleGroupNotFoundError(f"Unknown: {group_id}")
        cached = self._cache.get(norm)
        now = datetime.utcnow()
        if cached and cached.expires_at > now:
            return copy.deepcopy(cached.payload)

        payload = self._download(norm)
        exp = now + self._ttl
        payload["fetched_at"] = now.isoformat(timespec="seconds") + "Z"
        payload["expires_at"] = exp.isoformat(timespec="seconds") + "Z"
        payload["ttl_seconds"] = int(self._ttl.total_seconds())
        self._cache[norm] = _CacheEntry(exp, copy.deepcopy(payload))
        return payload

    def _download(self, norm: str) -> Dict[str, Any]:
        alias = self.GROUP_ALIAS[norm]
        try:
            r = requests.get(
                self.ENDPOINT,
                params={"GROUP": alias, "FORMAT": "TLE"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise TleProviderError(f"Connection error: {exc}") from exc
        if r.status_code != 200:
            raise TleProviderError(f"HTTP {r.status_code} for '{alias}'")
        entries = self._parse(r.text)
        if not entries:
            raise TleProviderError(f"No TLE data for '{alias}'")
        return {
            "group": norm, "alias": alias,
            "count": len(entries), "tles": entries,
            "source": "celestrak",
        }

    @staticmethod
    def _parse(text: str) -> List[Dict[str, Any]]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        entries: List[Dict[str, Any]] = []
        for i in range(0, len(lines) - 2, 3):
            name, l1, l2 = lines[i : i + 3]
            if not (l1.startswith("1 ") and l2.startswith("2 ")):
                continue
            norad = None
            tok = l1.split()
            if len(tok) >= 2:
                m = re.match(r"^(\d+)", tok[1])
                if m:
                    norad = m.group(1)
            entries.append({
                "name": name, "line1": l1, "line2": l2, "norad_id": norad,
            })
        return entries
