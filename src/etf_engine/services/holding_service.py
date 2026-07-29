from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import ManualProvider, YahooProvider
from etf_engine.services.holdings_history import HoldingsHistoryService
from etf_engine.settings import settings


@dataclass(frozen=True)
class HoldingSyncResult:
    rows: list[dict[str, Any]]
    fetched: bool
    source: str | None = None


class HoldingService:
    """Fetch and cache ETF holdings without replacing last-known-good on failure."""

    def path(self, etf_id: str) -> Path:
        return settings.normalized_dir / "holdings" / f"{etf_id}.json"

    def load(self, etf_id: str) -> list[dict[str, Any]]:
        path = self.path(etf_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def __init__(self, providers=None, history: HoldingsHistoryService | None = None):
        self.providers = providers or [ManualProvider(), YahooProvider()]
        self.history = history or HoldingsHistoryService()

    def sync(self, entity: ETFEntity) -> list[dict[str, Any]]:
        """Preserve the original list-returning API for callers."""
        return self.sync_with_status(entity).rows

    def sync_with_status(self, entity: ETFEntity) -> HoldingSyncResult:
        for provider in self.providers:
            try:
                rows = provider.fetch(entity)
            except Exception:
                continue
            if not rows:
                continue

            provider_dates = {row.get("as_of") for row in rows if row.get("as_of")}
            provider_as_of = provider_dates.pop() if len(provider_dates) == 1 else None
            generated_dates = {
                row.get("provider_generated_at") for row in rows if row.get("provider_generated_at")
            }
            provider_generated_at = generated_dates.pop() if len(generated_dates) == 1 else None
            self.history.record(
                entity.etf_id,
                rows,
                provider_generated_at=provider_generated_at,
                provider_as_of=provider_as_of,
            )
            path = self.path(entity.etf_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return HoldingSyncResult(rows=rows, fetched=True, source=provider.name)

        # A failed refresh must leave both cache and history untouched.
        return HoldingSyncResult(rows=self.load(entity.etf_id), fetched=False)


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
