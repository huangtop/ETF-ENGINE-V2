from datetime import date, timedelta

import pandas as pd

from etf_engine.models import ETFEntity
from etf_engine.providers.twse import TWSEPriceProvider
from etf_engine.providers.yahoo import YahooPriceProvider
from etf_engine.repository import PriceRepository


class PriceService:
    repair_lookback_days = 30

    def __init__(self, repo=None, providers=None):
        self.repo = repo or PriceRepository()
        self.providers = providers or [TWSEPriceProvider(), YahooPriceProvider()]

    def sync(self, entity: ETFEntity, start: date, end: date) -> pd.DataFrame:
        existing = self.repo.load(entity.etf_id)
        fetch_start = start
        if not existing.empty:
            last = pd.Timestamp(existing.index.max()).date()
            fetch_start = max(start, last - timedelta(days=self.repair_lookback_days))

        errors = []
        fresh = pd.DataFrame()
        for provider in self.providers:
            if not provider.supports(entity):
                continue
            try:
                fresh = provider.fetch(entity, fetch_start, end)
                if not fresh.empty:
                    break
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")

        if fresh.empty:
            if existing.empty:
                raise RuntimeError("; ".join(errors) or "no provider data")
            return existing.loc[str(start) : str(end)]

        combined = pd.concat([existing, fresh]).sort_index() if not existing.empty else fresh
        combined = combined[~combined.index.duplicated(keep="last")]
        self._validate_combined(existing, combined)
        self.repo.save(entity.etf_id, combined)
        return combined.loc[str(start) : str(end)]

    @staticmethod
    def _validate_combined(existing: pd.DataFrame, combined: pd.DataFrame) -> None:
        if combined.empty:
            raise ValueError("refusing to replace price cache with empty data")
        if not isinstance(combined.index, pd.DatetimeIndex):
            raise ValueError("price cache index must be a DatetimeIndex")
        if combined.index.has_duplicates or not combined.index.is_monotonic_increasing:
            raise ValueError("price cache dates must be unique and sorted")
        if "close" not in combined and "adj_close" not in combined:
            raise ValueError("price cache requires close or adj_close")
        if not existing.empty:
            lost_dates = existing.index.difference(combined.index)
            if len(lost_dates):
                raise ValueError("price refresh would remove historical dates")
