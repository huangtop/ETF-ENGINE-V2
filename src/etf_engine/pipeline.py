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
from etf_engine.services.provider_health import ProviderCircuitBreaker
from etf_engine.services.public_builder import build_public
from etf_engine.settings import settings

CORE_DAILY_HOLDINGS_IDS = {"TW-0050", "TW-006208", "US-SPY", "US-QQQ"}


def select_entities_for_run(
    entities: list[ETFEntity],
    cached_ids: set[str],
    bootstrap_limit: int,
    cursor: str | None,
    priority_ids: set[str] | None = None,
) -> tuple[list[ETFEntity], list[ETFEntity], str | None]:
    """Run cached and priority entities plus a bounded missing-cache rotation."""
    priority_ids = priority_ids or set()
    cached = [entity for entity in entities if entity.etf_id in cached_ids]
    priority_missing = sorted(
        (
            entity
            for entity in entities
            if entity.etf_id in priority_ids and entity.etf_id not in cached_ids
        ),
        key=lambda entity: entity.etf_id,
    )
    missing = sorted(
        (
            entity
            for entity in entities
            if entity.etf_id not in cached_ids and entity.etf_id not in priority_ids
        ),
        key=lambda entity: entity.etf_id,
    )
    if bootstrap_limit <= 0 or bootstrap_limit >= len(missing):
        selected_missing = missing
    else:
        after_cursor = [entity for entity in missing if not cursor or entity.etf_id > cursor]
        through_cursor = [entity for entity in missing if cursor and entity.etf_id <= cursor]
        selected_missing = (after_cursor + through_cursor)[:bootstrap_limit]
    attempted = priority_missing + selected_missing
    selected_ids = {entity.etf_id for entity in cached + attempted}
    scheduled = [entity for entity in entities if entity.etf_id in selected_ids]
    next_cursor = selected_missing[-1].etf_id if selected_missing else cursor
    return scheduled, attempted, next_cursor


def select_holdings_for_run(
    entities: list[ETFEntity],
    rotation_limit: int,
    cursor: str | None,
    core_ids: set[str] | None = None,
) -> tuple[list[ETFEntity], list[ETFEntity], str | None]:
    """Select daily core holdings plus a bounded round-robin non-core group."""
    core_ids = core_ids or CORE_DAILY_HOLDINGS_IDS
    core_ids = core_ids | {
        entity.etf_id for entity in entities if entity.management_style == "active"
    }
    core = [entity for entity in entities if entity.etf_id in core_ids]
    rotating = sorted(
        (entity for entity in entities if entity.etf_id not in core_ids),
        key=lambda entity: entity.etf_id,
    )
    if rotation_limit <= 0 or rotation_limit >= len(rotating):
        selected_rotating = rotating
    else:
        after_cursor = [
            entity for entity in rotating if not cursor or entity.etf_id > cursor
        ]
        through_cursor = [
            entity for entity in rotating if cursor and entity.etf_id <= cursor
        ]
        selected_rotating = (after_cursor + through_cursor)[:rotation_limit]
    selected_ids = {entity.etf_id for entity in core + selected_rotating}
    selected = [entity for entity in entities if entity.etf_id in selected_ids]
    next_cursor = selected_rotating[-1].etf_id if selected_rotating else cursor
    return selected, selected_rotating, next_cursor


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


def _configured_holdings_rotation_limit(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    raw = os.getenv("ETF_HOLDINGS_ROTATION_LIMIT", "40")
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise ValueError(
            "ETF_HOLDINGS_ROTATION_LIMIT must be a non-negative integer"
        ) from exc


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


def _replace_metrics_for_etfs(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    refreshed_etf_ids: set[str],
) -> list[dict[str, Any]]:
    retained = [row for row in previous if row.get("etf_id") not in refreshed_etf_ids]
    return _merge_metrics(retained, current)


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
    holdings_rotation_limit: int | None = None,
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
    holdings_limit = _configured_holdings_rotation_limit(holdings_rotation_limit)
    bootstrap_path = settings.state_dir / "bootstrap.json"
    bootstrap_state = _read_json(bootstrap_path, {})
    cursor_by_market = dict(bootstrap_state.get("cursor_by_market", {}))
    cursor = cursor_by_market.get(market)
    cached_ids = {
        entity.etf_id
        for entity in entities
        if (settings.normalized_dir / "prices" / f"{entity.etf_id}.parquet").exists()
    }
    priority_price_ids = {
        entity.etf_id for entity in entities if entity.management_style == "active"
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
                priority_price_ids,
            )
            scheduled_by_id.update({entity.etf_id: entity for entity in market_scheduled})
            attempted_new.extend(market_attempted)
            next_cursors[listing_market] = next_cursor
        scheduled = [entity for entity in entities if entity.etf_id in scheduled_by_id]
    else:
        scheduled, attempted_new, next_cursor = select_entities_for_run(
            entities, cached_ids, limit, cursor, priority_price_ids
        )
        next_cursors[market] = next_cursor

    if bootstrap_only:
        scheduled = attempted_new

    holdings_cursor_by_market = dict(
        bootstrap_state.get("holdings_cursor_by_market", {})
    )
    next_holdings_cursors: dict[str, str | None] = {}
    if market == "all" and holdings_limit > 0:
        markets = sorted({entity.listing_market for entity in entities})
        base, remainder = divmod(holdings_limit, len(markets))
        holdings_by_id: dict[str, ETFEntity] = {}
        holdings_rotating: list[ETFEntity] = []
        for index, listing_market in enumerate(markets):
            quota = base + (1 if index < remainder else 0)
            market_entities = [
                entity for entity in entities if entity.listing_market == listing_market
            ]
            market_selected, market_rotating, next_cursor = select_holdings_for_run(
                market_entities,
                quota,
                holdings_cursor_by_market.get(listing_market),
            )
            holdings_by_id.update({entity.etf_id: entity for entity in market_selected})
            holdings_rotating.extend(market_rotating)
            next_holdings_cursors[listing_market] = next_cursor
        holdings_scheduled = [
            entity for entity in entities if entity.etf_id in holdings_by_id
        ]
    else:
        holdings_scheduled, holdings_rotating, next_cursor = select_holdings_for_run(
            entities,
            holdings_limit,
            holdings_cursor_by_market.get(market),
        )
        next_holdings_cursors[market] = next_cursor

    if bootstrap_only:
        holdings_scheduled = attempted_new
        holdings_rotating = attempted_new

    service = PriceService()
    holding_service = HoldingService()
    end = date.today()
    start = end - timedelta(days=365 * 3 + 15)
    current_metrics: list[dict[str, Any]] = []
    metrics_refreshed: set[str] = set()
    errors: list[dict[str, str]] = []
    holdings_synced = 0
    holdings_updated: list[str] = []
    benchmark_cache: dict[str, Any] = {}
    price_breaker = ProviderCircuitBreaker()
    holdings_breaker = ProviderCircuitBreaker()
    prices_skipped_after_halt: list[str] = []
    holdings_skipped_after_halt: list[str] = []

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
        if price_breaker.halted:
            prices_skipped_after_halt.append(entity.etf_id)
            continue
        try:
            prices = service.sync(entity, start, end)
        except Exception as exc:
            price_breaker.observe([str(exc)])
            errors.append({"etf_id": entity.etf_id, "stage": "prices", "error": str(exc)})
        else:
            fetch_errors = getattr(service, "last_fetch_errors", [])
            if getattr(service, "used_cached_fallback", False) and fetch_errors:
                errors.append(
                    {
                        "etf_id": entity.etf_id,
                        "stage": "prices_cached_fallback",
                        "error": "; ".join(fetch_errors),
                    }
                )
            price_breaker.observe(fetch_errors)
            try:
                benchmark = get_benchmark(entity.benchmark_symbol)
            except Exception as exc:
                price_breaker.observe([str(exc)])
                errors.append(
                    {"etf_id": entity.etf_id, "stage": "benchmark", "error": str(exc)}
                )
                benchmark = None
            try:
                current_metrics.extend(
                    calculate_metrics(entity.etf_id, prices, benchmark)
                )
                metrics_refreshed.add(entity.etf_id)
            except Exception as exc:
                errors.append(
                    {"etf_id": entity.etf_id, "stage": "metrics", "error": str(exc)}
                )
    for entity in holdings_scheduled:
        if holdings_breaker.halted:
            holdings_skipped_after_halt.append(entity.etf_id)
            continue
        try:
            holding_result = holding_service.sync_with_status(entity)
            if holding_result.fetched:
                holdings_synced += 1
                holdings_updated.append(entity.etf_id)
            elif holding_result.errors:
                holdings_breaker.observe(list(holding_result.errors))
                errors.append(
                    {
                        "etf_id": entity.etf_id,
                        "stage": "holdings",
                        "error": "; ".join(holding_result.errors),
                    }
                )
        except Exception as exc:
            holdings_breaker.observe([str(exc)])
            errors.append({"etf_id": entity.etf_id, "stage": "holdings", "error": str(exc)})

    metrics_path = settings.normalized_dir / "metrics" / "latest.json"
    last_known_metrics = _merge_metrics(
        _load_public_metrics(entities),
        _read_json(metrics_path, []),
    )
    metrics = _replace_metrics_for_etfs(
        last_known_metrics,
        current_metrics,
        metrics_refreshed,
    )
    _write_json(metrics_path, metrics)

    cached_after = {
        entity.etf_id
        for entity in entities
        if (settings.normalized_dir / "prices" / f"{entity.etf_id}.parquet").exists()
    }
    cursor_by_market.update(next_cursors)
    holdings_cursor_by_market.update(next_holdings_cursors)
    bootstrap_payload = {
        "updated_at": end.isoformat(),
        "cursor_by_market": cursor_by_market,
        "holdings_cursor_by_market": holdings_cursor_by_market,
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
        "holdings_rotation_limit": holdings_limit,
        "holdings_scheduled": len(holdings_scheduled),
        "holdings_rotating": [entity.etf_id for entity in holdings_rotating],
        "holdings_updated": holdings_updated,
        "bootstrap_only": bootstrap_only,
        "published": publish,
        "provider_halted": price_breaker.halted or holdings_breaker.halted,
        "provider_halt_reason": price_breaker.halt_reason or holdings_breaker.halt_reason,
        "price_provider_halted": price_breaker.halted,
        "price_provider_halt_reason": price_breaker.halt_reason,
        "holdings_provider_halted": holdings_breaker.halted,
        "holdings_provider_halt_reason": holdings_breaker.halt_reason,
        "prices_skipped_after_provider_halt": prices_skipped_after_halt,
        "holdings_skipped_after_provider_halt": holdings_skipped_after_halt,
        "skipped_after_provider_halt": (
            prices_skipped_after_halt + holdings_skipped_after_halt
        ),
        "errors": errors,
    }
    _write_json(settings.state_dir / "last_run.json", state)
    if publish:
        build_public()
    return state
