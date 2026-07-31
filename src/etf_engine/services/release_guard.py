from __future__ import annotations

import json
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ReleaseValidation:
    baseline_counts: dict[str, int]
    candidate_counts: dict[str, int]
    errors: list[str]

    @property
    def passed(self) -> bool:
        return not self.errors


class ReleaseRejectedError(RuntimeError):
    def __init__(self, validation: ReleaseValidation) -> None:
        self.validation = validation
        super().__init__("public dataset rejected: " + "; ".join(validation.errors))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _items_by_id(root: Path) -> dict[str, dict[str, Any]]:
    rows = _read_json(root / "etfs.json", [])
    return {
        row["etf_id"]: row
        for row in rows
        if isinstance(row, dict) and row.get("etf_id")
    }


def _has_metric(item: dict[str, Any], code: str) -> bool:
    metric = item.get("metrics", {}).get(code, {})
    return isinstance(metric, dict) and metric.get("value") is not None


def _is_short_history_replacement(item: dict[str, Any]) -> bool:
    """Recognize a valid correction from mislabeled 1y metrics to inception data."""
    if not _has_metric(item, "total_return_since_inception"):
        return False
    data_years = item.get("metrics", {}).get("data_years", {}).get("value")
    return isinstance(data_years, (int, float)) and 0 <= data_years < 1


def _counts(items: dict[str, dict[str, Any]]) -> dict[str, int]:
    rows = list(items.values())
    holdings = [holding for row in rows for holding in row.get("top_holdings", [])]
    return {
        "etfs": len(rows),
        "TW": sum(row.get("listing_market") == "TW" for row in rows),
        "US": sum(row.get("listing_market") == "US" for row in rows),
        "metrics_ready": sum(bool(row.get("metrics")) for row in rows),
        "one_year_ready": sum(_has_metric(row, "total_return_1y") for row in rows),
        "latest_price_ready": sum(bool(row.get("latest_price")) for row in rows),
        "trend_ready": sum(bool(row.get("trend")) for row in rows),
        "holdings_rows": len(holdings),
        "etf_translations": sum(bool(row.get("name_zh")) for row in rows),
        "holding_translations": sum(bool(row.get("holding_name_zh")) for row in holdings),
    }


def _validate_internal_consistency(
    candidate_dir: Path,
    candidate: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    candidate_ids = set(candidate)
    market_rows = {
        market: _read_json(candidate_dir / "markets" / f"{market}.json", [])
        for market in ("TW", "US")
    }
    market_ids = {
        row.get("etf_id")
        for rows in market_rows.values()
        for row in rows
        if isinstance(row, dict)
    }
    if market_ids != candidate_ids:
        errors.append("market files do not match etfs.json")

    for etf_id, item in candidate.items():
        individual = _read_json(candidate_dir / "etf" / f"{etf_id}.json", None)
        if individual != item:
            errors.append(f"{etf_id}: individual JSON does not match etfs.json")

    expected_metrics = sorted(
        (
            item["etf_id"],
            metric_code,
            metric.get("value"),
            metric.get("unit", "ratio"),
        )
        for item in candidate.values()
        for metric_code, metric in item.get("metrics", {}).items()
    )
    actual_metrics = sorted(
        (
            row.get("etf_id"),
            row.get("metric_code"),
            row.get("value"),
            row.get("unit", "ratio"),
        )
        for row in _read_json(candidate_dir / "latest_metrics.json", [])
    )
    if actual_metrics != expected_metrics:
        errors.append("latest_metrics.json does not match ETF metrics")

    classifications = _read_json(candidate_dir / "classifications.json", [])
    orphan_ids = sorted(
        {
            row.get("etf_id")
            for row in classifications
            if isinstance(row, dict) and row.get("etf_id") not in candidate_ids
        }
    )
    if orphan_ids:
        errors.append(f"orphan classifications: {', '.join(orphan_ids[:5])}")

    manifest = _read_json(candidate_dir / "manifest.json", {})
    if manifest.get("etf_count") != len(candidate):
        errors.append("manifest ETF count does not match etfs.json")
    for market in ("TW", "US"):
        if manifest.get("markets", {}).get(market) != len(market_rows[market]):
            errors.append(f"manifest {market} count does not match market JSON")

    for etf_id, item in candidate.items():
        for holding in item.get("top_holdings", []):
            if holding.get("weight") is None:
                errors.append(f"{etf_id}: holding without weight")
                break

    return errors


def _holdings_content_hash(etf_id: str, holdings: list[dict[str, Any]]) -> str:
    content = sorted(
        [
            {
                "etf_id": etf_id,
                "holding_symbol": str(row["holding_symbol"]).strip().upper(),
                "weight": round(float(row["weight"]), 8),
                "source": str(row.get("source") or "unknown"),
            }
            for row in holdings
        ],
        key=lambda row: (row["holding_symbol"], row["source"]),
    )
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_holdings_history(
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    history_dir: Path | None,
) -> list[str]:
    if history_dir is None:
        return []
    index = _read_json(history_dir / "snapshot_index.json", {})
    errors = []
    for etf_id, entry in index.get("etfs", {}).items():
        current_snapshot_id = entry.get("current")
        item = candidate.get(etf_id)
        if not current_snapshot_id or item is None or not item.get("top_holdings"):
            continue
        previous = baseline.get(etf_id, {})
        if _holdings_content_hash(etf_id, previous.get("top_holdings", [])) == (
            _holdings_content_hash(etf_id, item["top_holdings"])
        ):
            # Do not block an unrelated release on pre-existing history debt. Any
            # newly changed holdings content must still match the history current.
            continue
        snapshot = _read_json(
            history_dir / "snapshots" / f"{current_snapshot_id}.json",
            {},
        )
        expected_hash = snapshot.get("content_sha256")
        actual_hash = _holdings_content_hash(etf_id, item["top_holdings"])
        if expected_hash and actual_hash != expected_hash:
            errors.append(f"{etf_id}: holdings cache does not match history current snapshot")
    return errors


def validate_candidate(
    baseline_dir: Path,
    candidate_dir: Path,
    history_dir: Path | None = None,
) -> ReleaseValidation:
    baseline = _items_by_id(baseline_dir)
    candidate = _items_by_id(candidate_dir)
    baseline_counts = _counts(baseline)
    candidate_counts = _counts(candidate)
    errors = _validate_internal_consistency(candidate_dir, candidate)
    errors.extend(_validate_holdings_history(baseline, candidate, history_dir))

    if baseline and set(candidate) != set(baseline):
        removed = sorted(set(baseline) - set(candidate))
        if removed:
            errors.append(f"ETF identities removed without lifecycle transition: {removed[:5]}")

    for etf_id in sorted(set(baseline) & set(candidate)):
        previous = baseline[etf_id]
        current = candidate[etf_id]
        previous_metrics = previous.get("metrics", {})
        for metric_code, metric in previous_metrics.items():
            if not isinstance(metric, dict) or metric.get("value") is None:
                continue
            short_history_replacement = (
                metric_code
                in {"total_return_1y", "annualized_return", "sharpe_ratio"}
                and _is_short_history_replacement(current)
            )
            if not _has_metric(current, metric_code) and not short_history_replacement:
                errors.append(f"{etf_id}: lost metric {metric_code}")

        if previous.get("latest_price") and not current.get("latest_price"):
            errors.append(f"{etf_id}: lost latest price")
        previous_price_date = str((previous.get("latest_price") or {}).get("date") or "")
        current_price_date = str((current.get("latest_price") or {}).get("date") or "")
        if previous_price_date and current_price_date < previous_price_date:
            errors.append(f"{etf_id}: latest price date moved backward")
        previous_liquidity_date = str((previous.get("liquidity") or {}).get("as_of") or "")
        current_liquidity_date = str((current.get("liquidity") or {}).get("as_of") or "")
        if previous_liquidity_date and current_liquidity_date < previous_liquidity_date:
            errors.append(f"{etf_id}: liquidity date moved backward")
        if previous.get("trend") and not current.get("trend"):
            errors.append(f"{etf_id}: lost trend")
        if len(current.get("trend", [])) < len(previous.get("trend", [])):
            errors.append(f"{etf_id}: trend history regressed")

        previous_holdings = previous.get("top_holdings", [])
        current_holdings = current.get("top_holdings", [])
        if previous_holdings and not current_holdings:
            errors.append(f"{etf_id}: holdings became empty")
        if previous_holdings and len(current_holdings) < max(1, len(previous_holdings) // 2):
            errors.append(f"{etf_id}: holdings coverage collapsed")

        if previous.get("name_zh") and not current.get("name_zh"):
            errors.append(f"{etf_id}: ETF translation disappeared")
        if (
            previous.get("name_zh")
            and current.get("name_zh")
            and previous["name_zh"] != current["name_zh"]
        ):
            errors.append(f"{etf_id}: existing ETF translation changed")
        previous_holding_names = {
            row.get("holding_symbol"): row.get("holding_name_zh")
            for row in previous_holdings
            if row.get("holding_symbol") and row.get("holding_name_zh")
        }
        current_by_symbol = {
            row.get("holding_symbol"): row for row in current_holdings if row.get("holding_symbol")
        }
        for symbol, name_zh in previous_holding_names.items():
            if symbol in current_by_symbol and not current_by_symbol[symbol].get("holding_name_zh"):
                errors.append(f"{etf_id}/{symbol}: holding translation disappeared ({name_zh})")
            elif (
                symbol in current_by_symbol
                and current_by_symbol[symbol].get("holding_name_zh") != name_zh
            ):
                errors.append(f"{etf_id}/{symbol}: existing holding translation changed")

        previous_by_symbol = {
            row.get("holding_symbol"): row
            for row in previous_holdings
            if row.get("holding_symbol")
        }
        for symbol, row in current_by_symbol.items():
            old = previous_by_symbol.get(symbol)
            if not old:
                continue
            same_content = (
                round(float(old.get("weight", -1)), 8)
                == round(float(row.get("weight", -2)), 8)
                and str(old.get("source") or "") == str(row.get("source") or "")
            )
            if same_content and old.get("as_of") and not row.get("as_of"):
                errors.append(f"{etf_id}/{symbol}: unchanged holding lost provider as_of")

    for field in (
        "metrics_ready",
        "latest_price_ready",
        "trend_ready",
        "etf_translations",
    ):
        if candidate_counts[field] < baseline_counts[field]:
            errors.append(
                f"global {field} regressed: "
                f"{baseline_counts[field]} -> {candidate_counts[field]}"
            )
    lost_one_year = baseline_counts["one_year_ready"] - candidate_counts["one_year_ready"]
    if lost_one_year > 0:
        baseline_short = sum(
            _is_short_history_replacement(item) for item in baseline.values()
        )
        candidate_short = sum(
            _is_short_history_replacement(item) for item in candidate.values()
        )
        if candidate_short - baseline_short < lost_one_year:
            errors.append(
                "global one_year_ready regressed without short-history replacement: "
                f"{baseline_counts['one_year_ready']} -> {candidate_counts['one_year_ready']}"
            )
    if baseline_counts["holdings_rows"] and (
        candidate_counts["holdings_rows"] < baseline_counts["holdings_rows"] * 0.9
    ):
        errors.append(
            "global holdings coverage regressed: "
            f"{baseline_counts['holdings_rows']} -> {candidate_counts['holdings_rows']}"
        )

    return ReleaseValidation(
        baseline_counts=baseline_counts,
        candidate_counts=candidate_counts,
        errors=errors,
    )


def promote_candidate(public_dir: Path, candidate_dir: Path) -> None:
    backup_dir = public_dir.with_name(f".{public_dir.name}-backup-{uuid4().hex}")
    had_baseline = public_dir.exists()
    try:
        if had_baseline:
            os.replace(public_dir, backup_dir)
        os.replace(candidate_dir, public_dir)
    except Exception:
        if not public_dir.exists() and backup_dir.exists():
            os.replace(backup_dir, public_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
