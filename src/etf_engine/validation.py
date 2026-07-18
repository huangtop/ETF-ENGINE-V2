from collections import Counter
from etf_engine.repository import SeedRepository

def validate()->list[str]:
    repo=SeedRepository(); entities=repo.entities(); classes=repo.classifications(); errors=[]
    ids=[x.etf_id for x in entities]
    for key,count in Counter(ids).items():
        if count>1: errors.append(f'duplicate etf_id: {key}')
    known=set(ids)
    for row in classes:
        if row.etf_id not in known: errors.append(f'orphan classification: {row.etf_id}')
    symbols=[x.quote_symbol for x in entities]
    for key,count in Counter(symbols).items():
        if count>1: errors.append(f'duplicate quote_symbol: {key}')
    return errors
