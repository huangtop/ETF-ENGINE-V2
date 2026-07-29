from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

import requests
from urllib3.exceptions import InsecureRequestWarning


TWSE_ETF_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
TPEX_ETF_URL = "https://info.tpex.org.tw/api/etfFilter"


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
            "https://openapi.twse.com.tw/v1/swagger.json",
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


class HttpClient(Protocol):
    def get(self, url: str, timeout: int) -> Any: ...

    def post(self, url: str, timeout: int, **kwargs: Any) -> Any: ...


def session() -> requests.Session:
    value = requests.Session()
    value.headers.update({"User-Agent": "ETF-Engine/2.5", "Accept": "application/json"})
    return value


def _json(client: HttpClient, url: str) -> Any:
    response = client.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _post_json(client: HttpClient, url: str) -> Any:
    try:
        response = client.post(url, timeout=30)
    except requests.exceptions.SSLError:
        # TPEx currently serves an incomplete certificate chain on some Python/
        # OpenSSL combinations. Retry only this official endpoint without CA
        # verification; sync validation still prevents partial-universe writes.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = client.post(url, timeout=30, verify=False)
    response.raise_for_status()
    return response.json()


def discover_catalog(client: HttpClient, source: OpenApiSource) -> dict[str, Any]:
    errors: list[str] = []
    for url in source.catalog_urls:
        try:
            data = _json(client, url)
            if isinstance(data, dict) and data.get("paths"):
                return data
        except Exception as exc:  # network dependent
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"Unable to discover {source.name} OpenAPI catalog: {'; '.join(errors)}")


def candidate_paths(catalog: dict[str, Any], keywords: tuple[str, ...]) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for path, spec in catalog.get("paths", {}).items():
        if not isinstance(spec, dict) or "get" not in spec:
            continue
        blob = json.dumps(spec, ensure_ascii=False).lower() + " " + path.lower()
        score = sum(10 for keyword in keywords if keyword.lower() in blob)
        if score:
            ranked.append((score, path))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [path for _, path in ranked]


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    normalized = {str(key).replace(" ", "").lower(): value for key, value in row.items()}
    wanted_names = [name.replace(" ", "").lower() for name in names]
    for wanted in wanted_names:
        if wanted in normalized:
            return normalized[wanted]
    for wanted in wanted_names:
        for actual, value in normalized.items():
            if wanted in actual:
                return value
    return None


def normalize_entity_row(
    row: dict[str, Any], exchange: str, source_name: str
) -> dict[str, Any] | None:
    code = (
        str(
            _first(
                row,
                ("證券代號", "基金代號", "stockNo", "代號", "code", "symbol"),
            )
            or ""
        )
        .strip()
        .upper()
    )
    name = str(
        _first(
            row,
            (
                "證券簡稱",
                "基金簡稱",
                "stockName",
                "證券名稱",
                "基金中文名稱",
                "基金名稱",
                "name",
            ),
        )
        or ""
    ).strip()
    if not CODE_RE.match(code) or not name:
        return None

    suffix = ".TWO" if exchange == "TPEx" else ".TW"
    fund_type = str(_first(row, ("基金類型", "fundType", "type")) or "")
    descriptor = f"{name} {fund_type}"
    structure = "standard"
    if code.endswith("L") or "正2" in descriptor or "槓桿" in descriptor:
        structure = "leveraged"
    elif code.endswith("R") or "反1" in descriptor or "反向" in descriptor:
        structure = "inverse"
    elif code.endswith("U") or "期貨" in descriptor:
        structure = "futures"

    management_style = "active" if code.endswith(("A", "D")) or "主動" in descriptor else "passive"
    if "債" in descriptor:
        asset_class = "fixed_income"
    elif any(word in descriptor for word in ("黃金", "原油", "期貨", "商品")):
        asset_class = "commodity"
    elif any(word in descriptor for word in ("平衡", "多資產")):
        asset_class = "balanced"
    else:
        asset_class = "equity"

    return {
        "etf_id": f"TW-{code}",
        "ticker": code,
        "quote_symbol": f"{code}{suffix}",
        "name": name,
        "short_name": name,
        "listing_market": "TW",
        "listing_exchange": exchange,
        "currency": "TWD",
        "benchmark_symbol": "0050.TW",
        "benchmark_name": _first(
            row,
            ("標的指數/追蹤指數名稱", "標的指數", "追蹤指數", "indexName", "benchmark"),
        ),
        "issuer": _first(row, ("發行人", "投信公司", "issuer")),
        "listing_date": _first(row, ("上市日期", "上櫃日期", "掛牌日期", "date")),
        "active": True,
        "product_status": "active",
        "management_style": management_style,
        "product_structure": structure,
        "asset_class": asset_class,
        "include_in_ranking": structure == "standard",
        "official_source": source_name,
    }


def fetch_twse_entities(client: HttpClient) -> list[dict[str, Any]]:
    payload = _json(client, TWSE_ETF_URL)
    if not isinstance(payload, list):
        raise RuntimeError("TWSE ETF endpoint returned an unexpected payload")
    return [
        normalized
        for row in payload
        if isinstance(row, dict) and (normalized := normalize_entity_row(row, "TWSE", "twse"))
    ]


def fetch_tpex_entities(client: HttpClient) -> list[dict[str, Any]]:
    payload = _post_json(client, TPEX_ETF_URL)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError("TPEx ETF endpoint returned an unexpected payload")
    return [
        normalized
        for row in rows
        if isinstance(row, dict) and (normalized := normalize_entity_row(row, "TPEx", "tpex"))
    ]


def fetch_entities_from_source(client: HttpClient, source: OpenApiSource) -> list[dict[str, Any]]:
    catalog = discover_catalog(client, source)
    paths = candidate_paths(catalog, ("etf", "指數股票型基金", "基金基本資料", "基金名稱"))
    results: dict[str, dict[str, Any]] = {}

    for path in paths[:12]:
        try:
            payload = _json(client, urljoin(source.base_url.rstrip("/") + "/", path.lstrip("/")))
        except Exception:
            continue

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("data", [])
        else:
            rows = []

        for raw in rows:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_entity_row(raw, source.exchange, source.name)
            if normalized:
                results[normalized["ticker"]] = normalized

        if len(results) >= 50:
            break

    return list(results.values())


def fetch_official_tw_entities() -> list[dict[str, Any]]:
    client = session()
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for source_name, fetcher in (
        ("twse", fetch_twse_entities),
        ("tpex", fetch_tpex_entities),
    ):
        try:
            for row in fetcher(client):
                rows[row["ticker"]] = row
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    if errors:
        raise RuntimeError("Official ETF collection incomplete. " + "; ".join(errors))

    return sorted(rows.values(), key=lambda row: row["ticker"])
