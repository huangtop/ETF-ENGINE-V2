from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import ManualProvider, YahooProvider
from etf_engine.settings import settings

class HoldingService:
    def __init__(self, providers=None): self.providers=providers or [ManualProvider(),YahooProvider()]
    def path(self,etf_id:str)->Path: return settings.normalized_dir/"holdings"/f"{etf_id}.json"
    def load(self,etf_id:str)->list[dict[str,Any]]:
        p=self.path(etf_id); return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    def _valid(self,entity:ETFEntity,rows:list[dict[str,Any]])->bool:
        if not rows: return False
        symbols=[x["holding_symbol"] for x in rows]
        if len(symbols)!=len(set(symbols)): return False
        total=sum(float(x["weight"]) for x in rows)
        if entity.asset_class=="equity" and not (0.20 <= total <= 1.15): return False
        return all(0 <= float(x["weight"]) <= 1 for x in rows)
    def sync(self,entity:ETFEntity)->list[dict[str,Any]]:
        errors=[]
        for provider in self.providers:
            try:
                rows=provider.fetch(entity)
                if self._valid(entity,rows):
                    p=self.path(entity.etf_id); p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                    self._write_state(entity.etf_id,"success",provider.name,len(rows),None)
                    return rows
            except Exception as exc: errors.append(f"{provider.name}: {exc}")
        cached=self.load(entity.etf_id)
        self._write_state(entity.etf_id,"cached" if cached else "failed",None,len(cached),"; ".join(errors))
        return cached
    def _write_state(self,etf_id,status,source,count,error):
        p=settings.state_dir/"holdings_sync.json"; state=json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        state[etf_id]={"status":status,"source":source,"holding_count":count,"error":error,"updated_at":datetime.now(timezone.utc).isoformat()}
        p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def overlap(left,right):
    l={x["holding_symbol"]:float(x["weight"]) for x in left}; r={x["holding_symbol"]:float(x["weight"]) for x in right}; shared=sorted(set(l)&set(r))
    details=[{"holding_symbol":s,"left_weight":round(l[s],6),"right_weight":round(r[s],6),"overlap_weight":round(min(l[s],r[s]),6)} for s in shared]
    details.sort(key=lambda x:x["overlap_weight"],reverse=True)
    return {"overlap_ratio":round(sum(x["overlap_weight"] for x in details),6),"shared_holdings_count":len(details),"shared_holdings":details}
