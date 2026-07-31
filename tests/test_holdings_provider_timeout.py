from types import SimpleNamespace

import pytest

from etf_engine.models import ETFEntity
from etf_engine.providers import holdings as holdings_provider


def entity():
    return ETFEntity(
        etf_id="US-TEST",
        ticker="TEST",
        quote_symbol="TEST",
        name="Test",
        listing_market="US",
        listing_exchange="US",
        currency="USD",
        benchmark_symbol="SPY",
    )


def test_yahoo_holdings_restores_alarm_after_success(monkeypatch):
    alarms = []
    handlers = []
    original_handler = object()
    monkeypatch.setattr(holdings_provider.signal, "getsignal", lambda _signal: original_handler)
    monkeypatch.setattr(
        holdings_provider.signal,
        "signal",
        lambda _signal, handler: handlers.append(handler),
    )
    monkeypatch.setattr(holdings_provider.signal, "alarm", alarms.append)

    import yfinance

    monkeypatch.setattr(
        yfinance,
        "Ticker",
        lambda _symbol: SimpleNamespace(
            funds_data=SimpleNamespace(
                top_holdings=[{"symbol": "NVDA", "weight": 10}]
            )
        ),
    )

    rows = holdings_provider.YahooProvider().fetch(entity())

    assert rows[0]["holding_symbol"] == "NVDA"
    assert alarms == [30, 0]
    assert handlers[-1] is original_handler


def test_yahoo_holdings_restores_alarm_after_failure(monkeypatch):
    alarms = []
    original_handler = object()
    monkeypatch.setattr(holdings_provider.signal, "getsignal", lambda _signal: original_handler)
    monkeypatch.setattr(holdings_provider.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(holdings_provider.signal, "alarm", alarms.append)

    import yfinance

    def fail(_symbol):
        raise RuntimeError("limited")

    monkeypatch.setattr(yfinance, "Ticker", fail)

    with pytest.raises(RuntimeError, match="limited"):
        holdings_provider.YahooProvider().fetch(entity())

    assert alarms == [30, 0]
