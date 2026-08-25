from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

from etf_engine.settings import settings


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
EXCHANGES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}

AI_TECH_TERMS = (
    "artificial intelligence", " ai ", "generative ai", "semiconductor", "chip",
    "robotics", "automation", "cloud", "cybersecurity", "cyber security",
    "data center", "digital infrastructure", "quantum", "photonics", "optics",
    "optical", "software", "technology", "uranium", "nuclear",
)
BROAD_MARKET_TERMS = (
    "s&p 500", "total stock market", "total market", "nasdaq 100", "nasdaq-100",
    "russell 1000", "russell 2000", "dow jones industrial", "total world",
    "all-world", "developed markets", "emerging markets", "large-cap", "mid-cap",
    "small-cap",
)
TACTICAL_TERMS = (
    "2x", "3x", "ultra", "leveraged", "inverse", "daily bull", "daily bear",
    "single stock", "single-stock",
)


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_symbol_directory(text: str, *, nasdaq: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    for row in reader:
        if not row or row.get("ETF") != "Y" or row.get("Test Issue") == "Y":
            continue
        symbol = (row.get("Symbol") if nasdaq else row.get("ACT Symbol")) or ""
        if not symbol or symbol.startswith("File Creation Time"):
            continue
        exchange_code = "Q" if nasdaq else (row.get("Exchange") or "")
        rows.append(
            {
                "ticker": symbol.strip().replace("$", "-"),
                "name": (row.get("Security Name") or symbol).strip(),
                "listing_exchange": "Nasdaq" if nasdaq else EXCHANGES.get(exchange_code, exchange_code),
            }
        )
    return rows


def fetch_official_us_etfs(session=requests) -> list[dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for url, nasdaq in ((NASDAQ_LISTED_URL, True), (OTHER_LISTED_URL, False)):
        response = session.get(url, timeout=30)
        response.raise_for_status()
        for row in parse_symbol_directory(response.text, nasdaq=nasdaq):
            results[row["ticker"]] = row
    return [results[ticker] for ticker in sorted(results)]


def candidate_scope(name: str) -> str | None:
    """Return the auto-enrollment scope for a relevant, non-tactical new ETF."""
    text = f" {name.lower()} "
    if any(term in text for term in TACTICAL_TERMS):
        return None
    if any(term in text for term in AI_TECH_TERMS):
        return "ai_technology"
    if any(term in text for term in BROAD_MARKET_TERMS):
        return "broad_market"
    return None


def sync(
    *,
    apply_new: bool = False,
    official_rows: list[dict[str, str]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Snapshot the official US ETF directory and optionally enroll new listings.

    The first run establishes a baseline. Later runs can automatically add only
    symbols that appeared since the previous official snapshot, preventing the
    curated seed from suddenly expanding by thousands of legacy funds.
    """
    today = today or date.today()
    official_rows = official_rows if official_rows is not None else fetch_official_us_etfs()
    if len(official_rows) < 1_000:
        raise RuntimeError(f"Official US ETF universe validation failed: only {len(official_rows)} rows")

    snapshot_path = settings.state_dir / "us_etf_universe.json"
    candidates_path = settings.state_dir / "us_etf_candidates.json"
    entities_path = settings.seed_dir / "entities.json"
    translations_path = settings.seed_dir / "translations_zh.json"
    previous = _read_json(snapshot_path, {})
    previous_symbols = set(previous.get("symbols", []))
    official_by_ticker = {row["ticker"]: row for row in official_rows}
    current_symbols = set(official_by_ticker)
    newly_listed = sorted(current_symbols - previous_symbols) if previous_symbols else []

    entities = _read_json(entities_path, [])
    translations = _read_json(translations_path, [])
    existing = {row["ticker"] for row in entities if row.get("listing_market") == "US"}
    all_missing = current_symbols - existing
    relevant_missing = sorted(
        ticker
        for ticker in all_missing
        if candidate_scope(official_by_ticker[ticker]["name"])
    )
    eligible = sorted(
        ticker
        for ticker in set(newly_listed) - existing
        if candidate_scope(official_by_ticker[ticker]["name"])
    )
    added: list[str] = []
    if apply_new:
        translation_ids = {row["etf_id"] for row in translations}
        for ticker in eligible:
            source = official_by_ticker[ticker]
            etf_id = f"US-{ticker}"
            entities.append(
                {
                    "etf_id": etf_id,
                    "ticker": ticker,
                    "quote_symbol": ticker,
                    "name": source["name"],
                    "short_name": ticker,
                    "listing_market": "US",
                    "listing_exchange": source["listing_exchange"],
                    "currency": "USD",
                    "benchmark_symbol": "SPY",
                    "benchmark_name": "Pending research",
                    "active": True,
                    "product_status": "active",
                    "first_seen_at": today.isoformat(),
                }
            )
            if etf_id not in translation_ids:
                # Keep the UI complete until a reviewed Traditional Chinese name is supplied.
                translations.append({"etf_id": etf_id, "name_zh": source["name"]})
            added.append(ticker)
        if added:
            _write_json(entities_path, entities)
            _write_json(translations_path, translations)

    generated_at = datetime.now(timezone.utc).isoformat()
    _write_json(
        candidates_path,
        {
            "generated_at": generated_at,
            "official_count": len(current_symbols),
            "new_since_previous_snapshot": newly_listed,
            "relevant_missing_from_curated_seed": relevant_missing,
            "auto_enrolled": added,
        },
    )
    _write_json(
        snapshot_path,
        {"generated_at": generated_at, "source": "Nasdaq Trader Symbol Directory", "symbols": sorted(current_symbols)},
    )
    return {
        "official_count": len(current_symbols),
        "new_since_previous_snapshot": len(newly_listed),
        "official_not_curated": len(all_missing),
        "relevant_missing_from_curated_seed": len(relevant_missing),
        "added": added,
        "baseline_created": not bool(previous_symbols),
    }
