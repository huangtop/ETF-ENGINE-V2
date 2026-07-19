from etf_engine.providers.official_openapi import normalize_entity_row


def test_normalize_twse_entity():
    row = normalize_entity_row(
        {"證券代號": "0050", "證券簡稱": "元大台灣50"},
        "TWSE",
        "twse",
    )
    assert row is not None
    assert row["etf_id"] == "TW-0050"
    assert row["quote_symbol"] == "0050.TW"
    assert row["product_structure"] == "standard"
