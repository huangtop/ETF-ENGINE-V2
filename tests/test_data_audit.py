from datetime import date

import pandas as pd

from etf_engine.models import ETFEntity
from etf_engine.services.data_audit import audit_price_caches


def entity(etf_id: str, market: str = "US") -> ETFEntity:
    return ETFEntity(
        etf_id=etf_id,
        ticker=etf_id.split("-")[1],
        quote_symbol=etf_id.split("-")[1],
        name=etf_id,
        listing_market=market,
        listing_exchange=market,
        currency="USD" if market == "US" else "TWD",
        benchmark_symbol="SPY" if market == "US" else "0050.TW",
    )


class Repository:
    def __init__(self, frames):
        self.frames = frames

    def load(self, etf_id):
        value = self.frames.get(etf_id, pd.DataFrame())
        if isinstance(value, Exception):
            raise value
        return value


def test_audit_reports_readiness_history_volume_and_missing_cache():
    index = pd.bdate_range(end="2026-07-29", periods=252)
    ready = pd.DataFrame(
        {"adj_close": range(252), "volume": range(252)},
        index=index,
    )

    result = audit_price_caches(
        [entity("US-SPY"), entity("TW-0050", "TW")],
        repository=Repository({"US-SPY": ready}),
        as_of=date(2026, 7, 30),
    )

    assert result["eligible"] == 2
    assert result["ready"] == 1
    assert result["missing"] == 1
    assert result["one_year_eligible"] == 1
    assert result["volume_ready"] == 1
    assert result["items"][0]["last_date"] == "2026-07-29"


def test_audit_marks_stale_and_unreadable_cache_invalid():
    stale = pd.DataFrame(
        {"close": [1.0]},
        index=pd.to_datetime(["2026-06-01"]),
    )
    result = audit_price_caches(
        [entity("US-OLD"), entity("US-BAD")],
        repository=Repository({"US-OLD": stale, "US-BAD": OSError("broken")}),
        as_of=date(2026, 7, 30),
    )

    assert result["invalid"] == 2
    assert "stale_price_cache" in result["items"][0]["issues"]
    assert result["items"][1]["issues"] == ["unreadable_cache: broken"]
