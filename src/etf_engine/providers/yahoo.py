from datetime import date, timedelta
import time
import random
import signal
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import PriceProvider
from etf_engine.models import ETFEntity


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("yfinance download timeout")


class YahooPriceProvider(PriceProvider):
    name = 'yahoo'
    
    def supports(self, entity: ETFEntity) -> bool:
        return True
    
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=3, max=30), reraise=True)
    def fetch(self, entity: ETFEntity, start: date, end: date) -> pd.DataFrame:
        # 隨機延遲 1-2 秒，避免規律性請求被識別為機器人
        time.sleep(random.uniform(1, 2))
        
        # 設置 30 秒超時，防止卡住
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)
        
        try:
            # Yahoo end date is exclusive.
            frame = yf.download(
                entity.quote_symbol,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                progress=False,
                threads=False
            )
        finally:
            signal.alarm(0)  # 取消超時
        
        if frame is None or frame.empty:
            return pd.DataFrame()
        
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        
        cols = {c.lower().replace(' ', '_'): c for c in frame.columns}
        out = pd.DataFrame(index=pd.to_datetime(frame.index).tz_localize(None))
        
        for target in ('open', 'high', 'low', 'close', 'adj_close', 'volume'):
            source = cols.get(target)
            if source is not None:
                out[target] = pd.to_numeric(frame[source], errors='coerce')
        
        if 'adj_close' not in out and 'close' in out:
            out['adj_close'] = out['close']
        
        out['source'] = self.name
        return out.dropna(subset=['close'])
