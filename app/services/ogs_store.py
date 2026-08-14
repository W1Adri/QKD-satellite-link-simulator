# ---------------------------------------------------------------------------
# app/services/ogs_store.py
# ---------------------------------------------------------------------------
# Purpose : JSON-file persistence for Optical Ground Station (OGS) records.
#
# Classes:
#   OGSStore – read / write / upsert / delete ground stations from a
#              ``ogs_locations.json`` file.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4


class OGSStore:
    """Manages a flat JSON list of ground station records."""

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        if not self.data_path.exists():
            self.data_path.write_text("[]", encoding="utf-8")

    def _read(self) -> List[Dict[str, Any]]:
        with self.data_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, data: List[Dict[str, Any]]) -> None:
        with self.data_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def list(self) -> List[Dict[str, Any]]:
        return self._read()

    def overwrite(self, payload: List[Dict[str, Any]]) -> None:
        self._write(payload)

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._read()
        identifier = payload.get("id") or f"station-{uuid4().hex[:8]}"
        payload = {**payload, "id": identifier}
        for idx, rec in enumerate(data):
            if rec.get("id") == identifier:
                data[idx] = payload
                self._write(data)
                return payload
        data.append(payload)
        self._write(data)
        return payload

    def is_builtin(self, station_id: str) -> bool:
        data = self._read()
        for rec in data:
            if rec.get("id") == station_id:
                return rec.get("builtin", False)
        return False

    def delete_all(self) -> None:
        self._write([])

    def delete_user_stations(self) -> None:
        """Delete only user-created stations, keeping built-in ones."""
        data = self._read()
        self._write([r for r in data if r.get("builtin", False)])

    def delete(self, station_id: str) -> bool:
        data = self._read()
        rec = next((r for r in data if r.get("id") == station_id), None)
        if rec is None:
            return False
        if rec.get("builtin", False):
            return False
        filtered = [r for r in data if r.get("id") != station_id]
        self._write(filtered)
        return True
