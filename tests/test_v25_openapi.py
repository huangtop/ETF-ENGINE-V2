from typing import Any

from etf_engine.providers.official_openapi import (
    fetch_tpex_entities,
    fetch_twse_entities,
    normalize_entity_row,
)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class FakeClient:
    def __init__(self, get_payload: Any = None, post_payload: Any = None) -> None:
        self.get_payload = get_payload
        self.post_payload = post_payload

    def get(self, url: str, timeout: int) -> FakeResponse:
        assert url
        assert timeout == 30
        return FakeResponse(self.get_payload)

    def post(self, url: str, timeout: int, **kwargs: Any) -> FakeResponse:
        assert url
        assert timeout == 30
        assert isinstance(kwargs, dict)
        return FakeResponse(self.post_payload)


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


def test_normalize_tpex_entity():
    row = normalize_entity_row(
        {
            "stockNo": "006201",
            "stockName": "元大富櫃50",
            "indexName": "櫃買富櫃五十指數",
            "issuer": "元大投信",
            "listingDate": "20110127",
        },
        "TPEx",
        "tpex",
    )
    assert row is not None
    assert row["etf_id"] == "TW-006201"
    assert row["quote_symbol"] == "006201.TWO"
    assert row["benchmark_name"] == "櫃買富櫃五十指數"
    assert row["issuer"] == "元大投信"


def test_normalize_product_types():
    leveraged = normalize_entity_row(
        {"基金代號": "00631L", "基金簡稱": "元大台灣50正2"},
        "TWSE",
        "twse",
    )
    bond = normalize_entity_row(
        {"基金代號": "00679B", "基金簡稱": "元大美債20年"},
        "TPEx",
        "tpex",
    )
    active = normalize_entity_row(
        {
            "基金代號": "00980A",
            "基金簡稱": "主動野村臺灣優選",
            "基金類型": "主動式交易所交易基金(股票)",
        },
        "TWSE",
        "twse",
    )
    assert leveraged and leveraged["product_structure"] == "leveraged"
    assert leveraged["include_in_ranking"] is False
    assert bond and bond["asset_class"] == "fixed_income"
    assert active and active["management_style"] == "active"


def test_fetch_explicit_official_endpoints():
    twse = fetch_twse_entities(
        FakeClient(
            get_payload=[
                {
                    "基金代號": "0050",
                    "基金簡稱": "元大台灣50",
                    "基金類型": "國內成分證券指數股票型基金(股票)",
                }
            ]
        )
    )
    tpex = fetch_tpex_entities(
        FakeClient(post_payload={"data": [{"stockNo": "006201", "stockName": "元大富櫃50"}]})
    )
    assert [row["ticker"] for row in twse] == ["0050"]
    assert [row["ticker"] for row in tpex] == ["006201"]


def test_exact_official_field_wins_over_similar_metadata():
    row = normalize_entity_row(
        {
            "基金代號": "0050",
            "基金簡稱": "元大台灣50",
            "經理公司總機": "(02)2717-5555",
        },
        "TWSE",
        "twse",
    )
    assert row is not None
    assert row["issuer"] is None
