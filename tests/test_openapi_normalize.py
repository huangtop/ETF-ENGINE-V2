from etf_engine.providers.official_openapi import normalize_entity_row

def test_normalize_0050():
    r=normalize_entity_row({"證券代號":"0050","證券簡稱":"元大台灣50"},"TWSE","twse")
    assert r["etf_id"] == "TW-0050"
    assert r["quote_symbol"] == "0050.TW"
