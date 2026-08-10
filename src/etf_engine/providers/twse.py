from datetime import date
import os
import random
import time

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from etf_engine.models import ETFEntity
from etf_engine.providers.base import PriceProvider


class TWSEPriceProvider(PriceProvider):
    name = "twse"
    endpoint = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

    def __init__(
        self, request_interval: float | None = None, jitter: float = 0.1
    ) -> None:
        configured = os.getenv("ETF_TWSE_REQUEST_INTERVAL", "0.2")
        self.request_interval = max(
            0.0, float(configured) if request_interval is None else request_interval
        )
        self.jitter = max(0.0, jitter)
        self._last_request_at: float | None = None

    def supports(self, entity: ETFEntity) -> bool:
        return entity.listing_exchange == "TWSE" and entity.ticker.isdigit()

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        delay = self.request_interval + random.uniform(0, self.jitter) - elapsed
        if delay > 0:
            time.sleep(delay)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
        reraise=True,
    )
    def _month(self, ticker: str, yyyymm01: str) -> dict:
        self._pace()
        response = requests.get(
            self.endpoint,
            params={"response": "json", "date": yyyymm01, "stockNo": ticker},
            timeout=20,
        )
        self._last_request_at = time.monotonic()
        if response.status_code in {429, 503}:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    time.sleep(min(30.0, max(0.0, float(retry_after))))
                except ValueError:
                    pass
        response.raise_for_status()
        return response.json()

    def fetch(self, entity: ETFEntity, start: date, end: date) -> pd.DataFrame:
        rows = []
        for month in pd.period_range(start=start, end=end, freq="M"):
            payload = self._month(
                entity.ticker, f"{month.year}{month.month:02d}01"
            )
            for row in payload.get("data", []):
                try:
                    year, month_number, day_number = map(int, row[0].split("/"))
                    day = pd.Timestamp(year + 1911, month_number, day_number)
                    if not (pd.Timestamp(start) <= day <= pd.Timestamp(end)):
                        continue
                    rows.append(
                        {
                            "date": day,
                            "volume": float(row[1].replace(",", "")),
                            "open": float(row[3].replace(",", "")),
                            "high": float(row[4].replace(",", "")),
                            "low": float(row[5].replace(",", "")),
                            "close": float(row[6].replace(",", "")),
                        }
                    )
                except (ValueError, IndexError):
                    continue
        if not rows:
            return pd.DataFrame()
        output = pd.DataFrame(rows).set_index("date").sort_index()
        output["adj_close"] = output["close"]
        output["source"] = self.name
        return output
