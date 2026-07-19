from __future__ import annotations
import argparse, json
from etf_engine.repository import SeedRepository
from etf_engine.services.holding_service import HoldingService

def sync(market="all",active_only=True):
    entities=SeedRepository().entities(); service=HoldingService(); done=failed=0
    for e in entities:
        if active_only and not e.active: continue
        if market!="all" and e.listing_market!=market: continue
        rows=service.sync(e)
        if rows: done+=1
        else: failed+=1
    return {"synced_or_cached":done,"failed":failed,"market":market}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--market",default="all",choices=("all","TW","US")); a=p.parse_args(); print(json.dumps(sync(a.market),ensure_ascii=False,indent=2))
if __name__=="__main__": main()
