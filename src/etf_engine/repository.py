import json
from pathlib import Path
import pandas as pd
from .models import ETFEntity, Classification
from .settings import settings

class SeedRepository:
    def entities(self) -> list[ETFEntity]:
        data=json.loads((settings.seed_dir/'entities.json').read_text(encoding='utf-8'))
        return [ETFEntity.model_validate(x) for x in data]
    def classifications(self) -> list[Classification]:
        data=json.loads((settings.seed_dir/'classifications.json').read_text(encoding='utf-8'))
        return [Classification.model_validate(x) for x in data]

class PriceRepository:
    def path(self, etf_id:str)->Path:
        return settings.normalized_dir/'prices'/f'{etf_id}.parquet'
    def load(self,etf_id:str)->pd.DataFrame:
        p=self.path(etf_id)
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()
    def save(self,etf_id:str,df:pd.DataFrame)->None:
        p=self.path(etf_id); p.parent.mkdir(parents=True,exist_ok=True)
        df.sort_index().to_parquet(p)
