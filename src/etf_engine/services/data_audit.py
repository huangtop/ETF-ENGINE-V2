from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from etf_engine.models import ETFEntity
from etf_engine.repository import PriceRepository


def audit_price_caches(
    entities: list[ETFEntity],
    *,
    repository: PriceRepository | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    repo = repository or PriceRepository()
    today = as_of or date.today()
    rows: list[dict[str, Any]] = []

    for entity in entities:
        issues: list[str] = []
        try:
            frame = repo.load(entity.etf_id)
        except Exception as exc:
            rows.append(
                {
                    "etf_id": entity.etf_id,
                    "market": entity.listing_market,
                    "status": "invalid",
                    "issues": [f"unreadable_cache: {exc}"],
                }
            )
            continue

        if frame.empty:
            rows.append(
                {
                    "etf_id": entity.etf_id,
                    "market": entity.listing_market,
                    "status": "missing",
                    "observations": 0,
                    "issues": ["missing_price_cache"],
                }
            )
            continue

        index = pd.DatetimeIndex(frame.index)
        if index.has_duplicates:
            issues.append("duplicate_dates")
        if not index.is_monotonic_increasing:
            issues.append("unsorted_dates")
        price_column = "adj_close" if "adj_close" in frame else "close"
        if price_column not in frame:
            issues.append("missing_price_column")
            valid_prices = 0
        else:
            valid_prices = int(frame[price_column].notna().sum())
            if valid_prices == 0:
                issues.append("empty_price_values")

        first_date = index.min().date()
        last_date = index.max().date()
        if last_date > today:
            issues.append("future_price_date")
        stale_days = (today - last_date).days
        stale_limit = 10 if entity.listing_market == "TW" else 7
        if stale_days > stale_limit:
            issues.append("stale_price_cache")

        if price_column in frame:
            numeric_prices = pd.to_numeric(frame[price_column], errors="coerce").dropna()
            if (numeric_prices <= 0).any():
                issues.append("nonpositive_price")

        volume_observations = int(frame["volume"].notna().sum()) if "volume" in frame else 0
        if "volume" in frame:
            numeric_volume = pd.to_numeric(frame["volume"], errors="coerce").dropna()
            if (numeric_volume < 0).any():
                issues.append("negative_volume")
        rows.append(
            {
                "etf_id": entity.etf_id,
                "market": entity.listing_market,
                "status": "invalid" if issues else "ready",
                "observations": len(frame),
                "valid_price_observations": valid_prices,
                "volume_observations": volume_observations,
                "first_date": first_date.isoformat(),
                "last_date": last_date.isoformat(),
                "stale_calendar_days": stale_days,
                "one_year_eligible": valid_prices >= 252,
                "issues": issues,
            }
        )

    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("ready", "missing", "invalid")
    }
    return {
        "as_of": today.isoformat(),
        "eligible": len(entities),
        "ready": counts["ready"],
        "missing": counts["missing"],
        "invalid": counts["invalid"],
        "one_year_eligible": sum(row.get("one_year_eligible", False) for row in rows),
        "volume_ready": sum(row.get("volume_observations", 0) > 0 for row in rows),
        "items": rows,
    }
