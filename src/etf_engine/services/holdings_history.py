from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from etf_engine.settings import settings


SCHEMA_VERSION = "1.0"
COVERAGE = "top_holdings_only"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class HoldingsHistoryService:
    """Append successful holdings observations and immutable content snapshots."""

    def __init__(
        self,
        history_dir: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.history_dir = history_dir or settings.root / "data" / "history" / "holdings"
        self.snapshots_dir = self.history_dir / "snapshots"
        self.clock = clock

    def record(
        self,
        etf_id: str,
        holdings: list[dict[str, Any]],
        *,
        provider_generated_at: str | None = None,
        provider_as_of: str | None = None,
        coverage: str = COVERAGE,
    ) -> dict[str, Any]:
        if not holdings:
            raise ValueError("cannot record an empty holdings snapshot")

        observed_at = isoformat_z(self.clock())
        content = self._canonical_content(etf_id, holdings)
        content_sha256 = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        index_path = self.history_dir / "snapshot_index.json"
        index = self._read(
            index_path,
            {"schema_version": SCHEMA_VERSION, "updated_at": observed_at, "etfs": {}},
        )
        entry = index["etfs"].setdefault(
            etf_id, {"current": None, "previous": None, "snapshots": []}
        )
        existing = next(
            (item for item in entry["snapshots"] if item["content_sha256"] == content_sha256),
            None,
        )
        snapshot_id = (
            existing["snapshot_id"]
            if existing
            else f"{observed_at[:10].replace('-', '')}-{content_sha256[:12]}"
        )
        content_changed = entry["current"] != snapshot_id

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"{snapshot_id}.json"
        snapshot_created = False
        if existing is None:
            snapshot = {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "observed_at": observed_at,
                "provider_generated_at": provider_generated_at,
                "provider_as_of": provider_as_of,
                "provider_as_of_status": (
                    "available" if provider_as_of is not None else "unavailable"
                ),
                "coverage": coverage,
                "etf_id": etf_id,
                "content_sha256": content_sha256,
                "holdings": content,
            }
            self._write_immutable(snapshot_path, snapshot)
            snapshot_created = True

        observations = self._read(
            self.history_dir / "observations.json",
            {"schema_version": SCHEMA_VERSION, "observations": []},
        )
        observations["observations"].append(
            {
                "observation_id": f"{observed_at}-{etf_id}-{uuid4().hex[:8]}",
                "observed_at": observed_at,
                "etf_id": etf_id,
                "snapshot_id": snapshot_id,
                "content_sha256": content_sha256,
                "content_changed": content_changed,
                "provider_generated_at": provider_generated_at,
                "provider_as_of": provider_as_of,
                "provider_as_of_status": (
                    "available" if provider_as_of is not None else "unavailable"
                ),
                "coverage": coverage,
            }
        )
        self._write_atomic(self.history_dir / "observations.json", observations)

        if content_changed:
            entry["previous"] = entry["current"]
            entry["current"] = snapshot_id
        if snapshot_created:
            entry["snapshots"].append(
                {
                    "snapshot_id": snapshot_id,
                    "observed_at": observed_at,
                    "content_sha256": content_sha256,
                    "path": f"snapshots/{snapshot_id}.json",
                }
            )
        index["updated_at"] = observed_at
        self._write_atomic(index_path, index)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "history_type": "etf_holdings",
            "coverage": "provider_specific",
            "updated_at": observed_at,
            "observation_count": len(observations["observations"]),
            "snapshot_count": sum(len(item["snapshots"]) for item in index["etfs"].values()),
            "etf_count": len(index["etfs"]),
            "snapshot_index": "snapshot_index.json",
            "observations": "observations.json",
            "snapshots_directory": "snapshots/",
        }
        self._write_atomic(self.history_dir / "manifest.json", manifest)
        return {
            "snapshot_id": snapshot_id,
            "snapshot_created": snapshot_created,
            "content_changed": content_changed,
        }

    @staticmethod
    def _canonical_content(etf_id: str, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        content = [
            {
                "etf_id": etf_id,
                "holding_symbol": str(row["holding_symbol"]).strip().upper(),
                "weight": round(float(row["weight"]), 8),
                "source": str(row.get("source") or "unknown"),
            }
            for row in holdings
        ]
        return sorted(content, key=lambda row: (row["holding_symbol"], row["source"]))

    @staticmethod
    def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_immutable(path: Path, data: dict[str, Any]) -> None:
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
        except FileExistsError:
            pass

    @staticmethod
    def _write_atomic(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
