from abc import ABC, abstractmethod
from datetime import date
import pandas as pd
from etf_engine.models import ETFEntity

class PriceProvider(ABC):
    name: str
    @abstractmethod
    def supports(self, entity: ETFEntity) -> bool: ...
    @abstractmethod
    def fetch(self, entity: ETFEntity, start: date, end: date) -> pd.DataFrame: ...
