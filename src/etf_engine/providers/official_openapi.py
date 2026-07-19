from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class OpenApiSource:
    name: str
    base_url: str
    catalog_urls: tuple[str, ...]
    exchange: str


SOURCES = (
    OpenApiSource(
        name="twse",
        base_url="https://openapi.twse.com.tw",
        catalog_urls=(
            "https://openapi.twse.com.tw/v1/openapi.json",
            "https://openapi.twse.com.tw/openapi.json",
            "https://openapi.twse.com.tw/swagger/v1/swagger.json",
        ),
        exchange="TWSE",
    ),
    OpenApiSource(
        name="tpex",
        base_url="https://www.tpex.org.tw",
        catalog_urls=(
            "https://www.tpex.org.tw/openapi/swagger.json",
            "https://www.tpex.org.tw/openapi/openapi.json",
            "https://www.tpex.org.tw/openapi/v1/openapi.json",
        ),
        exchange="TPEx",
    ),
)

CODE_RE = re.compile(r"^00\d{2,4}[A-Z]?$", re.I)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ETF-Engine/2.5", "Accept": "application/json"})
    return s


def _json(s: requests.Session, url: str) -> Any:
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def discover_catalog(s: requests.Session, source: OpenApiSource) -> dict[str, Any]:
    last: Exception | None = None
    for url in source.catalog_urls:
        try:
            data = _json(s, url)
            if isinstance(data, dict) and data.get("paths"):
                return data
        except Exception as exc:  # pragma: no cover - network dependent
            last = exc
    raise RuntimeError(f"Unable to discover {source.name} OpenAPI catalog: {last}")


def candidate_paths(catalog: dict[str, Any], keywords: tuple[str, ...]) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for path, spec in catalog.get("paths", {}).items():
        blob = json.dumps(spec, ensure_ascii=False).lower() + " " + path.lower()
        score = sum(10 for kw in keywords if kw.lower() in blob)
        if "get" in spec and score:
            ranked.append((score, path))
    ranked.sort(reverse=True)
    return [p for _, p in ranked]


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    normalized = {str(k).replace(" ", "").lower(): v for k, v in row.items()}
    for name in names:
        key = name.replace(" ", "").lower()
        for actual, value in normalized.items():
            if key == actual or key in actual:
                return value
    return None


def normalize_entity_row(row: dict[str, Any], exchange: str, source_name: str) -> dict[str, Any] | None:
    code = str(_first(row, ("證券代號", "基金代號", "代號", "code", "symbol")) or "").strip().upper()
    name = str(_first(row, ("證券簡稱", "基金簡稱", "證券名稱", "基金名稱", "name")) or "").strip()
    if not CODE_RE.match(code) or not name:
        return None
    suffix = ".TWO" if exchange == "TPEx" else ".TW"
    structure = "standard"
    if code.endswith("L") or "正2" in name:
        structure = "leveraged"
    elif code.endswith("R") or "反1" in name:
        structure = "inverse"
    elif code.endswith("U") or "期貨" in name:
        structure = "futures"
    management = "active" if code.endswith("A") or "主動" in name else "passive"
    asset = "fixed_income" if "債" in name else ("commodity" if any(x in name for x in ("黃金", "原油", "期貨")) else "equity")
    return {
        "etf_id": f"TW-{code}", "ticker": code, "quote_symbol": f"{code}{suffix}",
        "name": name, "short_name": name, "listing_market": "TW", "listing_exchange": exchange,
        "currency": "TWD", "benchmark_symbol": "0050.TW", "benchmark_name": _first(row, ("標的指數", "追蹤指數", "benchmark")),
        "issuer": _first(row, ("發行人", "投信公司", "經理公司", "issuer")),
        "listing_date": _first(row, ("上市日期", "上櫃日期", "掛牌日期", "date")),
        "active": True, "product_status": "active", "management_style": management,
        "product_structure": structure, "asset_class": asset,
        "include_in_ranking": structure == "standard", "official_source": source_name,
    }


def fetch_entities_from_source(s: requests.Session, source: OpenApiSource) -> list[dict[str, Any]]:
    catalog = discover_catalog(s, source)
    paths = candidate_paths(catalog, ("etf", "指數股票型基金", "基金基本資料", "基金名稱"))
    results: dict[str, dict[str, Any]] = {}
    for path in paths[:12]:
        try:
            payload = _json(s, source.base_url.rstrip("/") + path)
        except Exception:
            continue
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            row = normalize_entity_row(raw, source.exchange, source.name)
            if row:
                results[row["ticker"]] = row
        if len(results) >= 50:
            break
    return list(results.values())


def fetch_official_tw_entities() -> list[dict[str, Any]]:
    s = session()
    rows: dict[str, dict[str, Any]] = {}
    errors = []
    for source in SOURCES:
        try:
            for row in fetch_entities_from_source(s, source):
                rows[row["ticker"]] = row
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
    if not rows:
        raise RuntimeError("No official ETF entities collected. " + "; ".join(errors))
    return sorted(rows.values(), key=lambda x: x["ticker"])
