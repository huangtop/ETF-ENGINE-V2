from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import normalize

def test_normalize_percent():
    rows=normalize("TW-0050",[{"symbol":"2330","name":"TSMC","weight":"58%"}],"test")
    assert rows[0]["weight"] == 0.58

def test_entity_v25_fields():
    e=ETFEntity(etf_id="TW-0050",ticker="0050",quote_symbol="0050.TW",name="元大台灣50",listing_market="TW",listing_exchange="TWSE",currency="TWD",benchmark_symbol="0050.TW")
    assert e.product_structure == "standard"
