import pandas as pd

from etf_engine.services.public_builder import _price_metadata


def test_price_metadata_exposes_volume_and_full_year_eligibility():
    index = pd.date_range("2025-07-01", periods=260, freq="B")
    frame = pd.DataFrame(
        {
            "adj_close": [100 + value for value in range(260)],
            "volume": [1000 + value for value in range(260)],
        },
        index=index,
    )

    history, liquidity = _price_metadata(frame, "USD")

    assert history["one_year_eligible"] is True
    assert history["status"] == "complete_1y"
    assert history["observations"] == 260
    assert liquidity["latest_volume"] == 1259
    assert liquidity["observation_count"] == 20
    assert liquidity["average_dollar_volume_20d"] > 0
    assert liquidity["currency"] == "USD"


def test_short_history_and_missing_volume_are_explicit():
    index = pd.date_range("2026-06-01", periods=40, freq="B")
    frame = pd.DataFrame({"close": range(40)}, index=index)

    history, liquidity = _price_metadata(frame, "TWD")

    assert history["one_year_eligible"] is False
    assert history["status"] == "insufficient_history"
    assert liquidity is None
