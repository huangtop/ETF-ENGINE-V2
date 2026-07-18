from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from etf_engine.models import ETFEntity, HoldingRecord
from etf_engine.settings import settings


class HoldingService:
    """Fetch and cache ETF holdings.

    Yahoo's fund-data shape has changed across yfinance releases, so this adapter
    accepts both DataFrame and dict-like payloads. A failed refresh never deletes
    the last successful cache.
    """

    def path(self, etf_id: str) -> Path:
        return settings.normalized_dir / "holdings" / f"{etf_id}.json"

    def load(self, etf_id: str) -> list[dict[str, Any]]:
        path = self.path(etf_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def sync(self, entity: ETFEntity) -> list[dict[str, Any]]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(entity.quote_symbol)
            fund_data = ticker.funds_data
            raw = getattr(fund_data, "top_holdings", None)
            rows = self._normalize(entity.etf_id, raw)
            if rows:
                path = self.path(entity.etf_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return rows
        except Exception:
            pass
        return self.load(entity.etf_id)

    def _normalize(self, etf_id: str, raw: Any) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if isinstance(raw, pd.DataFrame):
            frame = raw.reset_index()
            records = frame.to_dict("records")
        elif isinstance(raw, dict):
            records = []
            for symbol, value in raw.items():
                if isinstance(value, dict):
                    records.append({"symbol": symbol, **value})
                else:
                    records.append({"symbol": symbol, "weight": value})
        elif isinstance(raw, list):
            records = raw
        else:
            return []

        normalized: list[dict[str, Any]] = []
        for row in records:
            lowered = {str(k).lower().replace(" ", "_"): v for k, v in row.items()}
            symbol = lowered.get("symbol") or lowered.get("holding_symbol") or lowered.get("ticker")
            if not symbol:
                symbol = lowered.get("index")
            weight = lowered.get("holding_percent")
            if weight is None:
                weight = lowered.get("weight")
            if weight is None:
                weight = lowered.get("percent_assets")
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                continue
            if weight > 1:
                weight /= 100.0
            name = lowered.get("name") or lowered.get("holding_name")
            record = HoldingRecord(
                etf_id=etf_id,
                holding_symbol=str(symbol).upper(),
                holding_name=str(name) if name else None,
                weight=weight,
                as_of=date.today(),
            )
            normalized.append(record.model_dump(mode="json"))
        normalized.sort(key=lambda x: x["weight"], reverse=True)
        return normalized[:100]


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
