from __future__ import annotations
import csv, json
from datetime import date
from pathlib import Path
from typing import Any, Protocol
import pandas as pd
from etf_engine.models import ETFEntity
from etf_engine.settings import settings

class HoldingsProvider(Protocol):
    name: str
    def fetch(self, entity: ETFEntity) -> list[dict[str, Any]]: ...


def normalize(etf_id: str, raw: Any, source: str) -> list[dict[str, Any]]:
    if raw is None: return []
    if isinstance(raw,pd.DataFrame): records=raw.reset_index().to_dict("records")
    elif isinstance(raw,list): records=raw
    elif isinstance(raw,dict): records=[({"symbol":k,**v} if isinstance(v,dict) else {"symbol":k,"weight":v}) for k,v in raw.items()]
    else: return []
    out=[]
    for rank,row in enumerate(records,1):
        low={str(k).lower().replace(" ","_"):v for k,v in row.items()}
        symbol=low.get("holding_symbol") or low.get("symbol") or low.get("ticker") or low.get("代號") or low.get("證券代號") or low.get("index")
        weight=low.get("weight") or low.get("holding_percent") or low.get("percent_assets") or low.get("權重") or low.get("持股權重")
        if symbol is None or weight is None: continue
        try:
            w=float(str(weight).replace("%","")); w=w/100 if w>1 else w
        except ValueError: continue
        if not (0 <= w <= 1): continue
        out.append({"etf_id":etf_id,"holding_symbol":str(symbol).strip().upper(),"holding_name":low.get("holding_name") or low.get("name") or low.get("名稱") or low.get("證券名稱"),"weight":round(w,8),"as_of":str(low.get("as_of") or low.get("date") or date.today()),"source":source,"rank":rank})
    dedup={}
    for row in out: dedup[row["holding_symbol"]]=row
    return sorted(dedup.values(),key=lambda x:x["weight"],reverse=True)

class ManualProvider:
    name="manual"
    def fetch(self,entity:ETFEntity)->list[dict[str,Any]]:
        for ext in ("json","csv"):
            p=settings.seed_dir/"holdings_manual"/f"{entity.etf_id}.{ext}"
            if not p.exists(): continue
            if ext=="json": raw=json.loads(p.read_text(encoding="utf-8"))
            else:
                with p.open(encoding="utf-8-sig",newline="") as f: raw=list(csv.DictReader(f))
            return normalize(entity.etf_id,raw,self.name)
        return []

class YahooProvider:
    name="yahoo"
    def fetch(self,entity:ETFEntity)->list[dict[str,Any]]:
        import yfinance as yf
        raw=getattr(yf.Ticker(entity.quote_symbol).funds_data,"top_holdings",None)
        return normalize(entity.etf_id,raw,self.name)
