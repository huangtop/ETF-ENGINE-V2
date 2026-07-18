from datetime import date
import pandas as pd
from etf_engine.models import ETFEntity
from etf_engine.providers.twse import TWSEPriceProvider
from etf_engine.providers.yahoo import YahooPriceProvider
from etf_engine.repository import PriceRepository

class PriceService:
    def __init__(self):
        self.repo=PriceRepository(); self.providers=[TWSEPriceProvider(),YahooPriceProvider()]
    def sync(self,entity:ETFEntity,start:date,end:date)->pd.DataFrame:
        existing=self.repo.load(entity.etf_id)
        fetch_start=start
        if not existing.empty:
            last=pd.Timestamp(existing.index.max()).date()
            if last>=end:return existing.loc[str(start):str(end)]
            fetch_start=max(start,last)
        errors=[]
        fresh=pd.DataFrame()
        for provider in self.providers:
            if not provider.supports(entity):continue
            try:
                fresh=provider.fetch(entity,fetch_start,end)
                if not fresh.empty:break
            except Exception as exc: errors.append(f'{provider.name}: {exc}')
        if fresh.empty and existing.empty: raise RuntimeError('; '.join(errors) or 'no provider data')
        combined=pd.concat([existing,fresh]).sort_index() if not existing.empty else fresh
        combined=combined[~combined.index.duplicated(keep='last')]
        self.repo.save(entity.etf_id,combined)
        return combined.loc[str(start):str(end)]
