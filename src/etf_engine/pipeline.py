from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from etf_engine.models import ETFEntity
from etf_engine.repository import SeedRepository
from etf_engine.services.holding_service import HoldingService
from etf_engine.services.metric_service import calculate_metrics
from etf_engine.services.price_service import PriceService
from etf_engine.services.public_builder import build_public
from etf_engine.settings import settings


def select_entities_for_run(
    entities: list[ETFEntity],
    cached_ids: set[str],
    bootstrap_limit: int,
    cursor: str | None,
) -> tuple[list[ETFEntity], list[ETFEntity], str | None]:
    """Run every cached entity plus a bounded, round-robin set without cache."""
    cached = [entity for entity in entities if entity.etf_id in cached_ids]
    missing = sorted(
        (entity for entity in entities if entity.etf_id not in cached_ids),
        key=lambda entity: entity.etf_id,
    )
    if bootstrap_limit <= 0 or bootstrap_limit >= len(missing):
        selected_missing = missing
    else:
        after_cursor = [entity for entity in missing if not cursor or entity.etf_id > cursor]
        through_cursor = [entity for entity in missing if cursor and entity.etf_id <= cursor]
        selected_missing = (after_cursor + through_cursor)[:bootstrap_limit]
    selected_ids = {entity.etf_id for entity in cached + selected_missing}
    scheduled = [entity for entity in entities if entity.etf_id in selected_ids]
    next_cursor = selected_missing[-1].etf_id if selected_missing else cursor
    return scheduled, selected_missing, next_cursor


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _configured_bootstrap_limit(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    raw = os.getenv("ETF_BOOTSTRAP_LIMIT", "0")
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise ValueError("ETF_BOOTSTRAP_LIMIT must be a non-negative integer") from exc


def _merge_metrics(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace successful metric observations without dropping other ETFs."""
    merged = {
        (row["etf_id"], row["metric_code"]): row
        for row in previous
        if row.get("etf_id") and row.get("metric_code")
    }
    for row in current:
        merged[(row["etf_id"], row["metric_code"])] = row
    return [merged[key] for key in sorted(merged)]


def _load_public_metrics(entities: list[ETFEntity]) -> list[dict[str, Any]]:
    """Recover committed last-known-good metrics when runner cache is empty."""
    entity_ids = {entity.etf_id for entity in entities}
    indexed_rows = _read_json(settings.public_dir / "latest_metrics.json", [])
    rows = [row for row in indexed_rows if row.get("etf_id") in entity_ids]
    recovered_ids = {row.get("etf_id") for row in rows}
    market_items = {
        row["etf_id"]: row
        for listing_market in ("TW", "US")
        for row in _read_json(
            settings.public_dir / "markets" / f"{listing_market}.json", []
        )
        if isinstance(row, dict) and row.get("etf_id") in entity_ids
    }
    for entity in entities:
        if entity.etf_id in recovered_ids:
            continue
        path = settings.public_dir / "etf" / f"{entity.etf_id}.json"
        payload = market_items.get(entity.etf_id) or _read_json(path, {})
        for metric_code, metric in payload.get("metrics", {}).items():
            if not isinstance(metric, dict) or metric.get("value") is None:
                continue
            rows.append(
                {
                    "etf_id": entity.etf_id,
                    "metric_code": metric_code,
                    "value": metric["value"],
                    "unit": metric.get("unit", "ratio"),
                }
            )
    return rows


def run(
    market: str = "all",
    bootstrap_limit: int | None = None,
    *,
    bootstrap_only: bool = False,
    publish: bool = True,
) -> dict[str, Any]:
    settings.ensure_dirs()
    seed = SeedRepository()
    all_entities = seed.entities()
    entities = [
        entity
        for entity in all_entities
        if entity.active and (market == "all" or entity.listing_market == market)
    ]
    limit = _configured_bootstrap_limit(bootstrap_limit)
    bootstrap_path = settings.state_dir / "bootstrap.json"
    bootstrap_state = _read_json(bootstrap_path, {})
    cursor_by_market = dict(bootstrap_state.get("cursor_by_market", {}))
    cursor = cursor_by_market.get(market)
    cached_ids = {
        entity.etf_id
        for entity in entities
        if (settings.normalized_dir / "prices" / f"{entity.etf_id}.parquet").exists()
    }
    next_cursors: dict[str, str | None] = {}
    if market == "all" and limit > 0:
        markets = sorted({entity.listing_market for entity in entities})
        base, remainder = divmod(limit, len(markets))
        scheduled_by_id: dict[str, ETFEntity] = {}
        attempted_new = []
        for index, listing_market in enumerate(markets):
            quota = base + (1 if index < remainder else 0)
            market_entities = [
                entity for entity in entities if entity.listing_market == listing_market
            ]
            market_scheduled, market_attempted, next_cursor = select_entities_for_run(
                market_entities,
                cached_ids,
                quota,
                cursor_by_market.get(listing_market),
            )
            scheduled_by_id.update({entity.etf_id: entity for entity in market_scheduled})
            attempted_new.extend(market_attempted)
            next_cursors[listing_market] = next_cursor
        scheduled = [entity for entity in entities if entity.etf_id in scheduled_by_id]
    else:
        scheduled, attempted_new, next_cursor = select_entities_for_run(
            entities, cached_ids, limit, cursor
        )
        next_cursors[market] = next_cursor

    if bootstrap_only:
        scheduled = attempted_new

    service = PriceService()
    holding_service = HoldingService()
    end = date.today()
    start = end - timedelta(days=365 * 3 + 15)
    current_metrics: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    holdings_synced = 0
    benchmark_cache: dict[str, Any] = {}

    def get_benchmark(symbol: str):
        if symbol in benchmark_cache:
            return benchmark_cache[symbol]
        target = next(
            (entity for entity in all_entities if entity.quote_symbol == symbol),
            None,
        )
        if target is None:
            market_prefix = "TW" if ".TW" in symbol else "US"
            target = ETFEntity(
                etf_id=f"{market_prefix}-BENCH",
                ticker=symbol.split(".")[0],
                quote_symbol=symbol,
                name=symbol,
                listing_market=market_prefix,
                listing_exchange="TWSE" if market_prefix == "TW" else "US",
                currency="TWD" if market_prefix == "TW" else "USD",
                benchmark_symbol=symbol,
            )
        benchmark_cache[symbol] = service.sync(target, start, end)
        return benchmark_cache[symbol]

    for entity in scheduled:
        try:
            prices = service.sync(entity, start, end)
            benchmark = get_benchmark(entity.benchmark_symbol)
            current_metrics.extend(calculate_metrics(entity.etf_id, prices, benchmark))
        except Exception as exc:
            errors.append({"etf_id": entity.etf_id, "stage": "prices", "error": str(exc)})
        try:
            holding_result = holding_service.sync_with_status(entity)
            if holding_result.fetched:
                holdings_synced += 1
        except Exception as exc:
            errors.append({"etf_id": entity.etf_id, "stage": "holdings", "error": str(exc)})

    metrics_path = settings.normalized_dir / "metrics" / "latest.json"
    last_known_metrics = _merge_metrics(
        _load_public_metrics(entities),
        _read_json(metrics_path, []),
    )
    metrics = _merge_metrics(last_known_metrics, current_metrics)
    _write_json(metrics_path, metrics)

    cached_after = {
        entity.etf_id
        for entity in entities
        if (settings.normalized_dir / "prices" / f"{entity.etf_id}.parquet").exists()
    }
    cursor_by_market.update(next_cursors)
    bootstrap_payload = {
        "updated_at": end.isoformat(),
        "cursor_by_market": cursor_by_market,
        "market": market,
        "limit": limit,
        "eligible": len(entities),
        "cached_before": len(cached_ids),
        "attempted_new": [entity.etf_id for entity in attempted_new],
        "ready_after": len(cached_after),
        "pending_after": len(entities) - len(cached_after),
    }
    _write_json(bootstrap_path, bootstrap_payload)

    state = {
        "run_date": end.isoformat(),
        "market": market,
        "eligible": len(entities),
        "processed": len(scheduled),
        "bootstrap_limit": limit,
        "bootstrap_attempted": len(attempted_new),
        "bootstrap_ready": len(cached_after),
        "bootstrap_pending": len(entities) - len(cached_after),
        "metric_rows": len(metrics),
        "holdings_synced": holdings_synced,
        "bootstrap_only": bootstrap_only,
        "published": publish,
        "errors": errors,
    }
    _write_json(settings.state_dir / "last_run.json", state)
    if publish:
        build_public()
    return state
