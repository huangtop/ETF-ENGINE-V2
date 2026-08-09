from __future__ import annotations

import csv
import io
import json
import re
import signal
import zipfile
from datetime import date, timedelta
from typing import Any, Protocol
from xml.etree import ElementTree

import pandas as pd
import requests

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
                # Never substitute our observation date for a provider's as-of.
                "as_of": provider_as_of,
                "source": source,
                "rank": rank,
            }
        )

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
