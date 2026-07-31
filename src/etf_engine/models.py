from datetime import date
from pydantic import BaseModel, Field


class ETFEntity(BaseModel):
    etf_id: str = Field(pattern=r"^[A-Z]{2}-")
    ticker: str
    quote_symbol: str
    name: str
    short_name: str | None = None
    listing_market: str
    listing_exchange: str
    currency: str
    benchmark_symbol: str
    benchmark_name: str | None = None
    issuer: str | None = None
    asset_class: str | None = None
    is_thematic: bool = False
    active: bool = True
    product_status: str = "active"
    management_style: str | None = None
    inception_date: date | None = None
    first_seen_at: date | None = None
    last_seen_at: date | None = None
    delisted_at: date | None = None


class Classification(BaseModel):
    etf_id: str
    dimension: str
    code: str
    source: str


class MetricRecord(BaseModel):
    etf_id: str
    metric_code: str
    value: float | None
    unit: str
    as_of: date
    period: str | None = None
    source: str = "calculated"


class HoldingRecord(BaseModel):
    etf_id: str
    holding_symbol: str
    holding_name: str | None = None
    weight: float = Field(ge=0)
    as_of: date | None = None
    source: str = "yahoo"
