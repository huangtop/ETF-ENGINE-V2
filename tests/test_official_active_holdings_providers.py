import html
import json
from datetime import date

import pytest
import requests

from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import (
    NomuraHoldingsProvider,
    UniPresidentHoldingsProvider,
)


def entity(etf_id: str) -> ETFEntity:
    ticker = etf_id.removeprefix("TW-")
    return ETFEntity(
        etf_id=etf_id,
        ticker=ticker,
        quote_symbol=f"{ticker}.TW",
        name=ticker,
        listing_market="TW",
        listing_exchange="TWSE",
        currency="TWD",
        benchmark_symbol="^TWII",
        management_style="active",
    )


class Response:
    def __init__(self, *, payload=None, text="", status_code=200):
        self.payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class UniSession:
    def __init__(self, page, listed=None):
        self.page = page
        self.listed = listed or [{"公司代號": "2330"}]

    def get(self, url, timeout, headers=None):
        if "openapi.twse.com.tw" in url:
            return Response(payload=self.listed)
        return Response(text=self.page)


class NomuraSession:
    def __init__(self, payload, listed=None):
        self.payload = payload
        self.listed = listed or [{"公司代號": "2330"}]

    def post(self, url, json, timeout):
        return Response(payload=self.payload)

    def get(self, url, timeout):
        return Response(payload=self.listed)


def uni_page(as_of="2026-08-10", count=10, total_weight=80.0):
    details = []
    for index in range(count):
        details.append(
            {
                "DetailCode": str(2330 + index),
                "DetailName": f"公司{index}",
                "NavRate": total_weight / count,
                "TranDate": f"{as_of}T00:00:00",
                "EditTime": f"{as_of}T16:30:00",
            }
        )
    payload = html.escape(json.dumps([{"AssetCode": "ST", "Details": details}]), quote=True)
    return f'<div id="DataAsset" data-content="{payload}"></div>'


def nomura_payload(as_of="2026/08/10", count=10, total_weight=80.0):
    rows = [
        [str(2330 + index), f"公司{index}", "1000", str(total_weight / count)]
        for index in range(count)
    ]
    return {
        "StatusCode": 0,
        "Message": "",
        "Entries": {
            "Data": {
                "FundAsset": {"NavDate": as_of},
                "Table": [{"TableTitle": "股票", "Rows": rows}],
            }
        },
    }


def test_uni_president_fetches_full_official_holdings():
    provider = UniPresidentHoldingsProvider(
        session=UniSession(uni_page()),
        today=lambda: date(2026, 8, 11),
    )

    rows = provider.fetch(entity("TW-00403A"))

    assert len(rows) == 10
    assert rows[0]["holding_symbol"] == "2330.TW"
    assert rows[1]["holding_symbol"] == "2331.TWO"
    assert rows[0]["weight"] == 0.08
    assert rows[0]["as_of"] == "2026-08-10"
    assert rows[0]["provider_generated_at"] == "2026-08-10T16:30:00"
    assert rows[0]["source"] == "uni_president"


def test_nomura_fetches_full_official_holdings():
    provider = NomuraHoldingsProvider(
        session=NomuraSession(nomura_payload()),
        today=lambda: date(2026, 8, 11),
    )

    rows = provider.fetch(entity("TW-00980A"))

    assert len(rows) == 10
    assert rows[0]["holding_symbol"] == "2330.TW"
    assert rows[0]["weight"] == 0.08
    assert rows[0]["as_of"] == "2026-08-10"
    assert rows[0]["source"] == "nomura"


@pytest.mark.parametrize(
    ("provider", "target"),
    [
        (
            UniPresidentHoldingsProvider(
                session=UniSession(uni_page(count=2)),
                today=lambda: date(2026, 8, 11),
            ),
            "TW-00403A",
        ),
        (
            NomuraHoldingsProvider(
                session=NomuraSession(nomura_payload(total_weight=20.0)),
                today=lambda: date(2026, 8, 11),
            ),
            "TW-00980A",
        ),
    ],
)
def test_official_provider_rejects_small_or_implausible_payload(provider, target):
    with pytest.raises(ValueError):
        provider.fetch(entity(target))


def test_unmapped_etf_does_not_use_official_provider():
    assert UniPresidentHoldingsProvider().fetch(entity("TW-0050")) == []
    assert NomuraHoldingsProvider().fetch(entity("TW-0050")) == []
