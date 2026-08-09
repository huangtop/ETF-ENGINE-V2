import json
import shutil
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from uuid import uuid4

import pandas as pd

from etf_engine.repository import SeedRepository, PriceRepository
from etf_engine.services.display_translations import (
    load_holding_translations,
    localize_holding,
)
from etf_engine.services.holding_service import HoldingService, overlap
from etf_engine.services.holdings_change_export import HoldingsChangeExporter
from etf_engine.services.release_guard import (
    ReleaseRejectedError,
    promote_candidate,
    validate_candidate,
)
from etf_engine.settings import settings


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_translations() -> dict[str, dict]:
    """Support either [{etf_id, name_zh}] or {etf_id: name_zh/dict} formats."""
    path = settings.seed_dir / "translations_zh.json"

    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result = {}

    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict) or not row.get("etf_id"):
                continue
            result[row["etf_id"]] = {
                "name_zh": row.get("name_zh"),
                "short_name_zh": row.get("short_name_zh"),
            }
    elif isinstance(raw, dict):
        for etf_id, value in raw.items():
            if isinstance(value, str):
                result[etf_id] = {"name_zh": value}
            elif isinstance(value, dict):
                result[etf_id] = {
                    "name_zh": value.get("name_zh"),
                    "short_name_zh": value.get("short_name_zh"),
                }

    return result


def load_research_profiles() -> dict[str, dict]:
    path = settings.seed_dir / "research_profiles.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["etf_id"]: {key: value for key, value in row.items() if key != "etf_id"}
        for row in rows
        if isinstance(row, dict) and row.get("etf_id")
    }


def _price_metadata(frame: pd.DataFrame, currency: str) -> tuple[dict, dict | None]:
    price_column = "adj_close" if "adj_close" in frame else "close"
    prices = frame[price_column].dropna()
    history = {
        "first_date": str(prices.index[0].date()),
        "last_date": str(prices.index[-1].date()),
        "observations": len(prices),
        "one_year_eligible": len(prices) >= 252,
        "status": "complete_1y" if len(prices) >= 252 else "insufficient_history",
    }
    if "volume" not in frame:
        return history, None

    volume = pd.to_numeric(frame["volume"], errors="coerce").dropna()
    if volume.empty:
        return history, None
    recent_volume = volume.iloc[-20:]
    aligned_prices = prices.reindex(recent_volume.index).dropna()
    aligned_volume = recent_volume.reindex(aligned_prices.index)
    average_volume = float(recent_volume.mean())
    latest_volume = float(volume.iloc[-1])
    average_dollar_volume = (
        float((aligned_prices * aligned_volume).mean()) if len(aligned_prices) else None
    )
    return history, {
        "as_of": str(volume.index[-1].date()),
        "latest_volume": round(latest_volume, 4),
        "average_volume_20d": round(average_volume, 4),
        "average_dollar_volume_20d": (
            round(average_dollar_volume, 4) if average_dollar_volume is not None else None
        ),
        "relative_volume_20d": (
            round(latest_volume / average_volume, 4) if average_volume else None
        ),
        "currency": currency,
        "volume_unit": "shares",
        "observation_count": len(recent_volume),
    }


def _render_public(
    target_dir: Path,
    baseline_dir: Path,
    holdings_updated_ids_override: set[str] | None = None,
    preserve_existing_prices: bool = False,
) -> None:
    repo = SeedRepository()
    entities = [x.model_dump(mode="json") for x in repo.entities()]
    classifications = [x.model_dump(mode="json") for x in repo.classifications()]
    translations = load_translations()
    holding_translations = load_holding_translations()
    research_profiles = load_research_profiles()

    metrics_path = settings.normalized_dir / "metrics" / "latest.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else []
    last_run_path = settings.state_dir / "last_run.json"
    last_run = (
        json.loads(last_run_path.read_text(encoding="utf-8")) if last_run_path.exists() else {}
    )
    failed_price_ids = {
        row.get("etf_id") for row in last_run.get("errors", []) if row.get("stage") == "prices"
    }
    holdings_updated_ids = (
        holdings_updated_ids_override
        if holdings_updated_ids_override is not None
        else set(last_run.get("holdings_updated", []))
    )
    existing_index_path = baseline_dir / "etfs.json"
    existing_index = (
        json.loads(existing_index_path.read_text(encoding="utf-8"))
        if existing_index_path.exists()
        else []
    )
    existing_market_items = [
        row
        for listing_market in ("TW", "US")
        for row in (
            json.loads(
                (baseline_dir / "markets" / f"{listing_market}.json").read_text(
                    encoding="utf-8"
                )
            )
            if (baseline_dir / "markets" / f"{listing_market}.json").exists()
            else []
        )
    ]
    existing_by_id = {
        row["etf_id"]: row
        for row in existing_index + existing_market_items
        if isinstance(row, dict) and row.get("etf_id")
    }

    metric_map = {}
    for row in metrics:
        metric_map.setdefault(row["etf_id"], {})[row["metric_code"]] = {
            "value": row["value"],
            "unit": row.get("unit", "ratio"),
        }

    class_map = {}
    for row in classifications:
        class_map.setdefault(row["etf_id"], []).append(
            {
                "dimension": row["dimension"],
                "code": row["code"],
            }
        )

    payload = []
    price_repo = PriceRepository()
    holding_service = HoldingService()
    holdings_map = {}
    reverse_holdings = {}

    for entity in entities:
        etf_id = entity["etf_id"]
        existing_path = baseline_dir / "etf" / f"{etf_id}.json"
        existing_file = (
            json.loads(existing_path.read_text(encoding="utf-8"))
            if existing_path.exists()
            else {}
        )
        existing = existing_by_id.get(etf_id) or existing_file
        translated = translations.get(etf_id, {})

        # Translation is applied here, rather than overwriting the canonical English name.
        name_zh = translated.get("name_zh")
        short_name_zh = translated.get("short_name_zh")
        display_name = name_zh or entity.get("name") or entity.get("ticker")
        display_short_name = (
            short_name_zh or name_zh or entity.get("short_name") or entity.get("ticker")
        )

        frame = pd.DataFrame() if preserve_existing_prices else price_repo.load(etf_id)
        latest_price = None
        trend = []
        price_history = existing.get("price_history")
        liquidity = existing.get("liquidity")
        prefer_existing_metrics = False
        bootstrap_status = "ready" if not frame.empty else "pending"
        if frame.empty and etf_id in failed_price_ids:
            bootstrap_status = "failed"

        if not frame.empty:
            series = frame["adj_close"] if "adj_close" in frame else frame["close"]
            series = series.dropna()

            if len(series):
                fresh_latest_price = {
                    "date": str(series.index[-1].date()),
                    "value": round(float(series.iloc[-1]), 4),
                    "currency": entity["currency"],
                }

                sample = series.iloc[-756:]
                norm = sample / sample.iloc[0] * 100
                fresh_trend = [
                    {
                        "date": str(date.date()),
                        "value": round(float(value), 2),
                    }
                    for date, value in norm.items()
                ]
                existing_latest_price = existing.get("latest_price") or {}
                existing_latest_date = str(existing_latest_price.get("date") or "")
                if existing_latest_date > fresh_latest_price["date"]:
                    latest_price = existing_latest_price
                    trend = existing.get("trend", [])
                    prefer_existing_metrics = True
                else:
                    latest_price = fresh_latest_price
                    trend_by_date = {
                        row["date"]: row
                        for row in existing.get("trend", []) + fresh_trend
                        if isinstance(row, dict) and row.get("date")
                    }
                    trend = [trend_by_date[key] for key in sorted(trend_by_date)][-756:]
                    price_history, liquidity = _price_metadata(frame, entity["currency"])
        elif existing.get("latest_price") or existing.get("trend") or existing.get("metrics"):
            # A partial/bootstrap run must not erase the last-known-good public record.
            latest_price = existing.get("latest_price")
            trend = existing.get("trend", [])
            bootstrap_status = "ready"

        cached_holdings = [
            localize_holding(row, holding_translations) for row in holding_service.load(etf_id)
        ]
        existing_holdings = existing.get("top_holdings", [])
        holdings = (
            cached_holdings
            if etf_id in holdings_updated_ids or not existing_holdings
            else existing_holdings
        )
        if not holdings and isinstance(existing.get("top_holdings"), list):
            holdings = existing["top_holdings"]
        holdings_map[etf_id] = holdings

        for row in holdings:
            reverse_holdings.setdefault(row["holding_symbol"], []).append(
                {
                    "holding_symbol": row["holding_symbol"],
                    "holding_name_en": row["holding_name_en"],
                    "holding_name_zh": row["holding_name_zh"],
                    "holding_display_name": row["display_name"],
                    "holding_display_label": row["display_label"],
                    "holding_bilingual_name": row["bilingual_name"],
                    "etf_id": etf_id,
                    "ticker": entity["ticker"],
                    "name": display_name,
                    "name_en": entity.get("name"),
                    "weight": row["weight"],
                }
            )

        holding_summary = {
            "holding_count": len(holdings),
            "top_10_weight": round(
                sum(float(x["weight"]) for x in holdings[:10]),
                6,
            ),
            "top_3_weight": round(
                sum(float(x["weight"]) for x in holdings[:3]),
                6,
            ),
        }

        item = {
            **entity,
            "name_en": entity.get("name"),
            "short_name_en": entity.get("short_name"),
            "name_zh": name_zh,
            "short_name_zh": short_name_zh,
            "display_name": display_name,
            "display_short_name": display_short_name,
            "display_label": f"({entity['ticker']}){display_name}",
            "bilingual_name": (
                f"{entity.get('name')}（{name_zh}）"
                if entity.get("name") and name_zh
                else display_name
            ),
            "classifications": class_map.get(etf_id, []),
            "metrics": (
                existing.get("metrics", {})
                if prefer_existing_metrics
                else metric_map.get(etf_id) or existing.get("metrics", {})
            ),
            "bootstrap_status": bootstrap_status,
            "latest_price": latest_price,
            "trend": trend,
            "price_history": price_history,
            "liquidity": liquidity,
            "top_holdings": holdings[:20],
            "holdings_summary": holding_summary,
            "research": research_profiles.get(
                etf_id,
                {
                    "tier": "context",
                    "nodes": [],
                    "roles": [],
                },
            ),
        }

        payload.append(item)
        write_json(target_dir / "etf" / f"{etf_id}.json", item)

    for symbol, rows in reverse_holdings.items():
        rows.sort(key=lambda x: x["weight"], reverse=True)
        write_json(target_dir / "holdings" / f"{symbol}.json", rows)

    write_json(target_dir / "holdings_index.json", reverse_holdings)

    ai_ids = {
        row["etf_id"]
        for row in classifications
        if row["dimension"] == "theme" and row["code"] == "artificial_intelligence"
    }

    overlap_index = []

    for left_id, right_id in combinations(sorted(ai_ids), 2):
        left = holdings_map.get(left_id, [])
        right = holdings_map.get(right_id, [])

        if not left or not right:
            continue

        result = overlap(left, right)
        row = {
            "left_etf_id": left_id,
            "right_etf_id": right_id,
            **result,
        }

        overlap_index.append({key: value for key, value in row.items() if key != "shared_holdings"})

        write_json(
            target_dir / "overlap" / f"{left_id}__{right_id}.json",
            row,
        )

    write_json(target_dir / "overlap_index.json", overlap_index)

    generated = datetime.now(timezone.utc).isoformat()
    bootstrap_counts = {
        status: sum(item["bootstrap_status"] == status for item in payload)
        for status in ("ready", "pending", "failed")
    }

    public_metrics = [
        {
            "etf_id": item["etf_id"],
            "metric_code": metric_code,
            "value": metric["value"],
            "unit": metric.get("unit", "ratio"),
        }
        for item in payload
        for metric_code, metric in item.get("metrics", {}).items()
    ]
    public_metrics.sort(key=lambda row: (row["etf_id"], row["metric_code"]))

    write_json(target_dir / "etfs.json", payload)
    write_json(target_dir / "classifications.json", classifications)
    write_json(target_dir / "latest_metrics.json", public_metrics)

    for market in ("TW", "US"):
        write_json(
            target_dir / "markets" / f"{market}.json",
            [item for item in payload if item["listing_market"] == market],
        )

    write_json(
        target_dir / "manifest.json",
        {
            "schema_version": "2.2",
            "generated_at": generated,
            "etf_count": len(payload),
            "holding_symbols": len(reverse_holdings),
            "overlap_pairs": len(overlap_index),
            "bootstrap": bootstrap_counts,
            "translations": {
                "locale": "zh-TW",
                "etf_count": len(translations),
                "holding_symbol_count": len(holding_translations),
                "fallback": "canonical_name",
            },
            "markets": {
                "TW": sum(x["listing_market"] == "TW" for x in payload),
                "US": sum(x["listing_market"] == "US" for x in payload),
            },
        },
    )
    HoldingsChangeExporter(public_dir=target_dir / "history" / "holdings").build()


def build_public(
    *,
    holdings_updated_ids_override: set[str] | None = None,
    preserve_existing_prices: bool = False,
):
    """Render, validate, and atomically publish a complete public dataset."""
    public_dir = settings.public_dir
    public_dir.parent.mkdir(parents=True, exist_ok=True)
    candidate_dir = public_dir.with_name(f".{public_dir.name}-candidate-{uuid4().hex}")
    try:
        _render_public(
            candidate_dir,
            public_dir,
            holdings_updated_ids_override,
            preserve_existing_prices,
        )
        history_dir = (
            settings.root / "data" / "history" / "holdings"
            if hasattr(settings, "root")
            else None
        )
        validation = validate_candidate(public_dir, candidate_dir, history_dir)
        if not validation.passed:
            raise ReleaseRejectedError(validation)
        promote_candidate(public_dir, candidate_dir)
        return validation
    finally:
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)


if __name__ == "__main__":
    build_public()
