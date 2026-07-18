import json
from datetime import date, timedelta
from etf_engine.repository import SeedRepository
from etf_engine.services.price_service import PriceService
from etf_engine.services.metric_service import calculate_metrics
from etf_engine.services.public_builder import build_public
from etf_engine.services.holding_service import HoldingService
from etf_engine.settings import settings

def run(market:str='all')->dict:
    settings.ensure_dirs(); seed=SeedRepository(); entities=[e for e in seed.entities() if e.active and (market=='all' or e.listing_market==market)]
    service=PriceService(); holding_service=HoldingService(); end=date.today(); start=end-timedelta(days=365*3+15); metrics=[]; errors=[]; holdings_synced=0; cache={}
    def get(symbol: str):
        if symbol in cache:
            return cache[symbol]
        target = next((e for e in seed.entities() if e.quote_symbol == symbol), None)
        if target is None:
            from etf_engine.models import ETFEntity
            # 為基準指數創建臨時實體，使用有效的 etf_id 格式
            market_prefix = 'TW' if '.TW' in symbol else 'US'
            target = ETFEntity(
                etf_id=f'{market_prefix}-BENCH',
                ticker=symbol.split('.')[0],
                quote_symbol=symbol,
                name=symbol,
                listing_market=market_prefix,
                listing_exchange='TWSE' if market_prefix == 'TW' else 'US',
                currency='TWD' if market_prefix == 'TW' else 'USD',
                benchmark_symbol=symbol
            )
        cache[symbol] = service.sync(target, start, end)
        return cache[symbol]
    for entity in entities:
        try:
            prices=service.sync(entity,start,end); benchmark=get(entity.benchmark_symbol)
            metrics.extend(calculate_metrics(entity.etf_id,prices,benchmark))
            if entity.listing_market == 'US':
                holding_service.sync(entity); holdings_synced += 1
        except Exception as exc: errors.append({'etf_id':entity.etf_id,'error':str(exc)})
    p=settings.normalized_dir/'metrics'/'latest.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    state={'run_date':end.isoformat(),'market':market,'processed':len(entities),'metric_rows':len(metrics),'holdings_synced':holdings_synced,'errors':errors}
    (settings.state_dir/'last_run.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    build_public(); return state
