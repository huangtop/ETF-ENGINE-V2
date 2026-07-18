from datetime import date
import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import PriceProvider
from etf_engine.models import ETFEntity

class TWSEPriceProvider(PriceProvider):
    name='twse'
    endpoint='https://www.twse.com.tw/exchangeReport/STOCK_DAY'
    def supports(self,entity:ETFEntity)->bool:
        return entity.listing_exchange=='TWSE' and entity.ticker.isdigit()
    @retry(stop=stop_after_attempt(3),wait=wait_exponential(min=1,max=8),reraise=True)
    def _month(self,ticker:str,yyyymm01:str)->dict:
        response=requests.get(self.endpoint,params={'response':'json','date':yyyymm01,'stockNo':ticker},timeout=20)
        response.raise_for_status(); return response.json()
    def fetch(self,entity:ETFEntity,start:date,end:date)->pd.DataFrame:
        rows=[]
        for month in pd.period_range(start=start,end=end,freq='M'):
            payload=self._month(entity.ticker,f'{month.year}{month.month:02d}01')
            for row in payload.get('data',[]):
                try:
                    y,m,d=map(int,row[0].split('/')); day=pd.Timestamp(y+1911,m,d)
                    if not (pd.Timestamp(start)<=day<=pd.Timestamp(end)): continue
                    rows.append({'date':day,'volume':float(row[1].replace(',','')),'open':float(row[3].replace(',','')),
                      'high':float(row[4].replace(',','')),'low':float(row[5].replace(',','')),'close':float(row[6].replace(',',''))})
                except (ValueError,IndexError): continue
        if not rows:return pd.DataFrame()
        out=pd.DataFrame(rows).set_index('date').sort_index(); out['adj_close']=out['close']; out['source']=self.name
        return out
