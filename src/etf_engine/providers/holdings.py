from __future__ import annotations

import csv
import json
from datetime import date
from typing import Any, Protocol

import pandas as pd

from etf_engine.models import ETFEntity
from etf_engine.settings import settings


class HoldingsProvider(Protocol):
    name: str

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        ...


def normalize(etf_id: str, raw: Any, source: str) -> list[dict[str, Any]]:
    if raw is None:
        return []

    if isinstance(raw, pd.DataFrame):
        records = raw.reset_index().to_dict("records")
    elif isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = [
            {"symbol": key, **value}
            if isinstance(value, dict)
            else {"symbol": key, "weight": value}
            for key, value in raw.items()
        ]
    else:
        return []

    result: list[dict[str, Any]] = []
    for rank, row in enumerate(records, 1):
        normalized = {
            str(key).lower().replace(" ", "_"): value for key, value in row.items()
        }
        symbol = (
            normalized.get("holding_symbol")
            or normalized.get("symbol")
            or normalized.get("ticker")
            or normalized.get("代號")
            or normalized.get("證券代號")
            or normalized.get("index")
        )
        weight = (
            normalized.get("weight")
            or normalized.get("holding_percent")
            or normalized.get("percent_assets")
            or normalized.get("權重")
            or normalized.get("持股權重")
        )
        if symbol is None or weight is None:
            continue

        try:
            parsed_weight = float(str(weight).replace("%", ""))
            if parsed_weight > 1:
                parsed_weight /= 100
        except (TypeError, ValueError):
            continue

        if not 0 <= parsed_weight <= 1:
            continue

        result.append(
            {
                "etf_id": etf_id,
                "holding_symbol": str(symbol).strip().upper(),
                "holding_name": (
                    normalized.get("holding_name")
                    or normalized.get("name")
                    or normalized.get("名稱")
                    or normalized.get("證券名稱")
                ),
                "weight": round(parsed_weight, 8),
                "as_of": str(
                    normalized.get("as_of")
                    or normalized.get("date")
                    or date.today()
                ),
                "source": source,
                "rank": rank,
            }
        )

    deduplicated = {row["holding_symbol"]: row for row in result}
    return sorted(
        deduplicated.values(), key=lambda row: row["weight"], reverse=True
    )


class ManualProvider:
    name = "manual"

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        for extension in ("json", "csv"):
            path = (
                settings.seed_dir
                / "holdings_manual"
                / f"{entity.etf_id}.{extension}"
            )
            if not path.exists():
                continue
            if extension == "json":
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    raw = list(csv.DictReader(handle))
            return normalize(entity.etf_id, raw, self.name)
        return []


class YahooProvider:
    name = "yahoo"

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        import yfinance as yf

        funds_data = getattr(yf.Ticker(entity.quote_symbol), "funds_data", None)
        raw = getattr(funds_data, "top_holdings", None) if funds_data else None
        return normalize(entity.etf_id, raw, self.name)
