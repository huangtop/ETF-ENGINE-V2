from __future__ import annotations

import csv
import html
import io
import json
import re
import signal
import ssl
import zipfile
from datetime import date, timedelta
from typing import Any, Protocol
from xml.etree import ElementTree

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

from etf_engine.models import ETFEntity
from etf_engine.settings import settings


def optional_provider_value(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "nat", "none"} else None


class HoldingsProvider(Protocol):
    name: str

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]: ...


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
        normalized = {str(key).lower().replace(" ", "_"): value for key, value in row.items()}
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
            or normalized.get("權重(%)")
            or normalized.get("持股權重")
        )
        if symbol is None or weight is None:
            continue

        try:
            weight_text = str(weight).strip()
            parsed_weight = float(weight_text.replace("%", ""))
            if "%" in weight_text or parsed_weight > 1:
                parsed_weight /= 100
        except (TypeError, ValueError):
            continue

        if not 0 <= parsed_weight <= 1:
            continue

        provider_as_of = optional_provider_value(normalized.get("as_of"))
        if provider_as_of is None:
            provider_as_of = optional_provider_value(normalized.get("date"))

        item = {
            "etf_id": etf_id,
            "holding_symbol": str(symbol).strip().upper(),
            "holding_name": (
                normalized.get("holding_name")
                or normalized.get("name")
                or normalized.get("名稱")
                or normalized.get("證券名稱")
            ),
            "weight": round(parsed_weight, 8),
            # Never substitute our observation date for a provider's as-of.
            "as_of": provider_as_of,
            "source": source,
            "rank": rank,
        }
        provider_generated_at = optional_provider_value(normalized.get("provider_generated_at"))
        if provider_generated_at is not None:
            item["provider_generated_at"] = provider_generated_at
        result.append(item)

    deduplicated = {row["holding_symbol"]: row for row in result}
    return sorted(deduplicated.values(), key=lambda row: row["weight"], reverse=True)


class ManualProvider:
    name = "manual"

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        for extension in ("json", "csv"):
            path = settings.seed_dir / "holdings_manual" / f"{entity.etf_id}.{extension}"
            if not path.exists():
                continue
            if extension == "json":
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    raw = list(csv.DictReader(handle))
            return normalize(entity.etf_id, raw, self.name)
        return []


def _official_rows_valid(
    rows: list[dict[str, Any]],
    provider_as_of: str,
    *,
    today,
    max_age_days: int,
) -> None:
    if len(rows) < 10:
        raise ValueError(f"official holdings coverage too small: {len(rows)}")
    try:
        as_of = date.fromisoformat(provider_as_of)
    except (TypeError, ValueError) as exc:
        raise ValueError("official holdings have no valid provider date") from exc
    age = (today() - as_of).days
    if age < 0 or age > max_age_days:
        raise ValueError(f"official holdings date is stale or future: {provider_as_of}")
    total_weight = sum(float(row["weight"]) for row in rows)
    if not 0.5 <= total_weight <= 1.05:
        raise ValueError(f"implausible total weight {total_weight:.4f}")


class _TaiwanSymbolMixin:
    twse_symbols_endpoint = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    timeout_seconds = 30

    def _add_market_suffixes(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        listed_symbols = self._listed_symbols()
        for row in rows:
            symbol = str(row["holding_symbol"]).strip().upper()
            overseas = re.fullmatch(r"([A-Z][A-Z0-9.-]*)\s+[A-Z]{2}", symbol)
            if overseas:
                row["holding_symbol"] = overseas.group(1)
            elif re.fullmatch(r"\d{4,6}", symbol):
                row["holding_symbol"] = f"{symbol}.{'TW' if symbol in listed_symbols else 'TWO'}"
        return rows

    def _listed_symbols(self) -> set[str]:
        cached = getattr(self, "_twse_listed_symbols", None)
        if cached is not None:
            return cached
        try:
            response = self.session.get(
                self.twse_symbols_endpoint,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"official TWSE symbol lookup failed: {exc}") from exc
        symbols = {
            str(row.get("公司代號", "")).strip()
            for row in payload
            if isinstance(row, dict)
        }
        self._twse_listed_symbols = symbols
        return symbols


class UniPresidentHoldingsProvider(_TaiwanSymbolMixin):
    """Fetch full portfolio holdings embedded in Uni-President's official page."""

    name = "uni_president"
    coverage = "full_portfolio"
    authoritative = True
    endpoint = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={fund_code}"
    fund_codes = {
        "TW-00403A": "63YTW",
        "TW-00981A": "49YTW",
        "TW-00988A": "61YTW",
    }
    max_age_days = 10

    def __init__(self, session: requests.Session | None = None, today=None):
        self.session = session or requests.Session()
        self.today = today or date.today

    def supports(self, entity: ETFEntity) -> bool:
        return entity.etf_id in self.fund_codes

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        fund_code = self.fund_codes.get(entity.etf_id)
        if fund_code is None:
            return []
        try:
            response = self.session.get(
                self.endpoint.format(fund_code=fund_code),
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 ETF-ENGINE-V2"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"official holdings request failed: {exc}") from exc

        matched = re.search(
            r'id=["\']DataAsset["\'][^>]*data-content=["\']([^"\']+)["\']',
            response.text,
        )
        if matched is None:
            raise RuntimeError("official holdings payload not found")
        try:
            assets = json.loads(html.unescape(matched.group(1)))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("official holdings payload is invalid") from exc
        stock = next(
            (item for item in assets if item.get("AssetCode") == "ST"),
            None,
        )
        details = stock.get("Details") if isinstance(stock, dict) else None
        if not isinstance(details, list):
            raise RuntimeError("official stock holdings are missing")

        records = []
        provider_dates = set()
        for item in details:
            provider_as_of = str(item.get("TranDate") or "")[:10]
            provider_dates.add(provider_as_of)
            generated_at = str(item.get("EditTime") or stock.get("EditDate") or "")
            records.append(
                {
                    "symbol": item.get("DetailCode"),
                    "name": item.get("DetailName"),
                    "weight": f"{item.get('NavRate')}%",
                    "as_of": provider_as_of,
                    "provider_generated_at": generated_at or None,
                }
            )
        if len(provider_dates) != 1:
            raise RuntimeError("official holdings contain inconsistent provider dates")
        provider_as_of = provider_dates.pop()
        rows = normalize(entity.etf_id, records, self.name)
        _official_rows_valid(
            rows,
            provider_as_of,
            today=self.today,
            max_age_days=self.max_age_days,
        )
        return self._add_market_suffixes(rows)


class NomuraHoldingsProvider(_TaiwanSymbolMixin):
    """Fetch full portfolio holdings from Nomura's official ETF API."""

    name = "nomura"
    coverage = "full_portfolio"
    authoritative = True
    endpoint = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
    fund_ids = {
        "TW-00980A": "00980A",
        "TW-00985A": "00985A",
        "TW-00999A": "00999A",
    }
    max_age_days = 10

    def __init__(self, session: requests.Session | None = None, today=None):
        self.session = session or self._session()
        self.today = today or date.today

    @staticmethod
    def _session() -> requests.Session:
        """Keep TLS verification while tolerating Nomura's non-strict chain."""
        context = ssl.create_default_context()
        strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict:
            context.verify_flags &= ~strict

        class Adapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = context
                return super().init_poolmanager(*args, **kwargs)

        session = requests.Session()
        session.mount("https://www.nomurafunds.com.tw", Adapter())
        return session

    def supports(self, entity: ETFEntity) -> bool:
        return entity.etf_id in self.fund_ids

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        fund_id = self.fund_ids.get(entity.etf_id)
        if fund_id is None:
            return []
        try:
            response = self.session.post(
                self.endpoint,
                json={"FundID": fund_id, "SearchDate": None},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"official holdings request failed: {exc}") from exc
        if payload.get("StatusCode") != 0:
            raise RuntimeError(
                f"official holdings API failed: {payload.get('Message') or 'unknown error'}"
            )
        entries = payload.get("Entries") or {}
        data = entries.get("Data") or {}
        fund_asset = data.get("FundAsset") or {}
        provider_as_of = str(fund_asset.get("NavDate") or "").replace("/", "-")
        table = next(
            (item for item in data.get("Table") or [] if item.get("TableTitle") == "股票"),
            None,
        )
        if table is None:
            raise RuntimeError("official stock holdings are missing")
        records = [
            {
                "symbol": row[0],
                "name": row[1],
                "weight": f"{row[3]}%",
                "as_of": provider_as_of,
            }
            for row in table.get("Rows") or []
            if isinstance(row, list) and len(row) >= 4
        ]
        rows = normalize(entity.etf_id, records, self.name)
        _official_rows_valid(
            rows,
            provider_as_of,
            today=self.today,
            max_age_days=self.max_age_days,
        )
        return self._add_market_suffixes(rows)


class FuhwaProvider:
    """Fetch full daily fund assets from Fuhwa's official Excel endpoint."""

    name = "fuhwa"
    coverage = "full_portfolio"
    authoritative = True
    endpoint = "https://www.fhtrust.com.tw/api/assetsExcel/{fund_id}/{date}"
    fund_ids = {"TW-00991A": "ETF23"}
    max_lookback_days = 10
    timeout_seconds = 30

    def __init__(self, session: requests.Session | None = None, today=None):
        self.session = session or requests.Session()
        self.today = today or date.today

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        fund_id = self.fund_ids.get(entity.etf_id)
        if fund_id is None:
            return []

        errors = []
        for offset in range(self.max_lookback_days + 1):
            requested_date = self.today() - timedelta(days=offset)
            url = self.endpoint.format(
                fund_id=fund_id,
                date=requested_date.strftime("%Y%m%d"),
            )
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                raise RuntimeError(f"official holdings request failed: {exc}") from exc
            if response.status_code in {400, 404}:
                continue
            try:
                response.raise_for_status()
            except requests.RequestException:
                errors.append(f"{requested_date.isoformat()}: HTTP {response.status_code}")
                continue

            try:
                provider_as_of, records = self._parse_workbook(response.content)
            except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
                errors.append(f"{requested_date.isoformat()}: {exc}")
                continue
            if provider_as_of != requested_date.isoformat():
                errors.append(
                    f"{requested_date.isoformat()}: workbook date is {provider_as_of}"
                )
                continue

            rows = normalize(entity.etf_id, records, self.name)
            if not rows:
                errors.append(f"{requested_date.isoformat()}: empty official holdings")
                continue
            total_weight = sum(float(row["weight"]) for row in rows)
            if not 0.5 <= total_weight <= 1.05:
                errors.append(
                    f"{requested_date.isoformat()}: implausible total weight {total_weight:.4f}"
                )
                continue
            return self._add_market_suffixes(rows)

        detail = "; ".join(errors[-3:]) or "no workbook in lookback window"
        raise RuntimeError(f"no valid official holdings workbook: {detail}")

    def supports(self, entity: ETFEntity) -> bool:
        return entity.etf_id in self.fund_ids

    @staticmethod
    def _parse_workbook(content: bytes) -> tuple[str, list[dict[str, Any]]]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            shared = FuhwaProvider._shared_strings(archive)
            root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//x:sheetData/x:row", namespace):
            values = []
            for cell in row.findall("x:c", namespace):
                value = cell.findtext("x:v", default="", namespaces=namespace)
                if cell.get("t") == "s" and value:
                    value = shared[int(value)]
                values.append(value)
            rows.append(values)

        flattened = [str(value).strip() for row in rows for value in row]
        date_text = next((value for value in flattened if value.startswith("日期:")), "")
        matched = re.search(r"(\d{4})/(\d{2})/(\d{2})", date_text)
        if matched is None:
            raise ValueError("workbook has no provider date")
        provider_as_of = "-".join(matched.groups())

        header_index = next(
            (index for index, row in enumerate(rows) if "證券代號" in row and "權重(%)" in row),
            None,
        )
        if header_index is None:
            raise ValueError("workbook holdings header not found")
        header = rows[header_index]
        records = []
        for values in rows[header_index + 1 :]:
            padded = values + [""] * (len(header) - len(values))
            record = dict(zip(header, padded, strict=False))
            symbol = str(record.get("證券代號", "")).strip()
            weight = str(record.get("權重(%)", "")).strip()
            if re.fullmatch(r"\d{4,6}", symbol) and weight.endswith("%"):
                record["as_of"] = provider_as_of
                records.append(record)
        if len(records) < 10:
            raise ValueError(f"official holdings coverage too small: {len(records)}")
        return provider_as_of, records

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        return ["".join(node.itertext()) for node in root.findall("x:si", namespace)]

    def _add_market_suffixes(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        listed_symbols = self._listed_symbols()
        for row in rows:
            symbol = row["holding_symbol"]
            row["holding_symbol"] = f"{symbol}.{'TW' if symbol in listed_symbols else 'TWO'}"
        return rows

    def _listed_symbols(self) -> set[str]:
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        try:
            response = self.session.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"official TWSE symbol lookup failed: {exc}") from exc
        return {
            str(row.get("公司代號", "")).strip()
            for row in payload
            if isinstance(row, dict)
        }


class YahooProvider:
    name = "yahoo"
    timeout_seconds = 30

    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]:
        import yfinance as yf

        supports_alarm = hasattr(signal, "SIGALRM")
        previous_handler = None
        if supports_alarm:
            previous_handler = signal.getsignal(signal.SIGALRM)

            def timeout_handler(_signum, _frame):
                raise TimeoutError("yahoo holdings timeout")

            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(self.timeout_seconds)
        try:
            funds_data = getattr(yf.Ticker(entity.quote_symbol), "funds_data", None)
            raw = getattr(funds_data, "top_holdings", None) if funds_data else None
            return normalize(entity.etf_id, raw, self.name)
        finally:
            if supports_alarm:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous_handler)
