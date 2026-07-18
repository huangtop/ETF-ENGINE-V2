from datetime import date, timedelta
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import PriceProvider
from etf_engine.models import ETFEntity

class YahooPriceProvider(PriceProvider):
    name='yahoo'
    def supports(self, entity: ETFEntity) -> bool: return True
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2,max=15), reraise=True)
    def fetch(self, entity: ETFEntity, start: date, end: date) -> pd.DataFrame:
        # Yahoo end date is exclusive.
        frame=yf.download(entity.quote_symbol,start=start.isoformat(),end=(end+timedelta(days=1)).isoformat(),auto_adjust=False,progress=False,threads=False)
        if frame.empty: return pd.DataFrame()
        if isinstance(frame.columns,pd.MultiIndex): frame.columns=frame.columns.get_level_values(0)
        cols={c.lower().replace(' ','_'):c for c in frame.columns}
        out=pd.DataFrame(index=pd.to_datetime(frame.index).tz_localize(None))
        for target in ('open','high','low','close','adj_close','volume'):
            source=cols.get(target)
            if source is not None: out[target]=pd.to_numeric(frame[source],errors='coerce')
        if 'adj_close' not in out and 'close' in out: out['adj_close']=out['close']
        out['source']=self.name
        return out.dropna(subset=['close'])
