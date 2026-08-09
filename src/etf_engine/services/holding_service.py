from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import FuhwaProvider, ManualProvider, YahooProvider
from etf_engine.services.holdings_history import HoldingsHistoryService
from etf_engine.settings import settings


@dataclass(frozen=True)
class HoldingSyncResult:
    rows: list[dict[str, Any]]
    fetched: bool
    source: str | None = None
    errors: tuple[str, ...] = ()


class HoldingService:
    """Fetch and cache ETF holdings without replacing last-known-good on failure."""

    def path(self, etf_id: str) -> Path:
        return settings.normalized_dir / "holdings" / f"{etf_id}.json"

    def load(self, etf_id: str) -> list[dict[str, Any]]:
        path = self.path(etf_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def __init__(self, providers=None, history: HoldingsHistoryService | None = None):
        self.providers = providers or [ManualProvider(), FuhwaProvider(), YahooProvider()]
        self.history = history or HoldingsHistoryService()

    def sync(self, entity: ETFEntity) -> list[dict[str, Any]]:
        """Preserve the original list-returning API for callers."""
        return self.sync_with_status(entity).rows

    def sync_with_status(self, entity: ETFEntity) -> HoldingSyncResult:
        errors = []
        for provider in self.providers:
            try:
                rows = provider.fetch(entity)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                if getattr(provider, "authoritative", False) and provider.supports(entity):
                    break
                continue
            if not rows:
                if getattr(provider, "authoritative", False) and provider.supports(entity):
                    errors.append(f"{provider.name}: official holdings were empty")
                    break
                continue

            rows = self._preserve_unchanged_metadata(self.load(entity.etf_id), rows)

            provider_dates = {row.get("as_of") for row in rows if row.get("as_of")}
            provider_as_of = provider_dates.pop() if len(provider_dates) == 1 else None
            generated_dates = {
                row.get("provider_generated_at") for row in rows if row.get("provider_generated_at")
            }
            provider_generated_at = generated_dates.pop() if len(generated_dates) == 1 else None
            self._write_cache_atomic(entity.etf_id, rows)
            self.history.record(
                entity.etf_id,
                rows,
                provider_generated_at=provider_generated_at,
                provider_as_of=provider_as_of,
                coverage=getattr(provider, "coverage", "top_holdings_only"),
            )
            return HoldingSyncResult(rows=rows, fetched=True, source=provider.name)

        # A failed refresh must leave both cache and history untouched.
        return HoldingSyncResult(
            rows=self.load(entity.etf_id),
            fetched=False,
            errors=tuple(errors),
        )

    @staticmethod
    def _preserve_unchanged_metadata(
        previous: list[dict[str, Any]],
        current: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        previous_by_symbol = {
            str(row.get("holding_symbol") or "").upper(): row for row in previous
        }
        merged = []
        for row in current:
            item = dict(row)
            old = previous_by_symbol.get(str(item.get("holding_symbol") or "").upper())
            same_content = old and (
                round(float(old.get("weight", -1)), 8)
                == round(float(item.get("weight", -2)), 8)
                and str(old.get("source") or "") == str(item.get("source") or "")
            )
            if same_content:
                for field in ("holding_name", "as_of", "provider_generated_at"):
                    if not item.get(field) and old.get(field):
                        item[field] = old[field]
            merged.append(item)
        return merged

    def _write_cache_atomic(self, etf_id: str, rows: list[dict[str, Any]]) -> None:
        path = self.path(etf_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def overlap(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    """Weighted overlap: sum of the lower weight for every shared holding."""
    lmap = {x["holding_symbol"]: float(x["weight"]) for x in left}
    rmap = {x["holding_symbol"]: float(x["weight"]) for x in right}
    shared = sorted(set(lmap) & set(rmap))
    details = [
        {
            "holding_symbol": symbol,
            "left_weight": round(lmap[symbol], 6),
            "right_weight": round(rmap[symbol], 6),
            "overlap_weight": round(min(lmap[symbol], rmap[symbol]), 6),
        }
        for symbol in shared
    ]
    details.sort(key=lambda x: x["overlap_weight"], reverse=True)
    return {
        "overlap_ratio": round(sum(x["overlap_weight"] for x in details), 6),
        "shared_holdings_count": len(details),
        "shared_holdings": details,
    }
