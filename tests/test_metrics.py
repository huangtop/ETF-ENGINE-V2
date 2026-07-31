import pandas as pd
from etf_engine.services.metric_service import calculate_metrics


def test_metrics_smoke():
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    etf = pd.DataFrame({"adj_close": [100 + i * 0.1 for i in range(260)]}, index=idx)
    benchmark = pd.DataFrame({"adj_close": [100 + i * 0.08 for i in range(260)]}, index=idx)
    rows = calculate_metrics("US-TEST", etf, benchmark)
    codes = {x["metric_code"] for x in rows}
    assert {"total_return_1y", "sharpe_ratio", "beta", "max_drawdown"} <= codes


def test_short_history_is_not_labeled_as_one_year_return():
    index = pd.date_range("2026-06-01", periods=40, freq="B")
    prices = pd.DataFrame(
        {"adj_close": [100 + index * 0.1 for index in range(40)]},
        index=index,
    )

    rows = calculate_metrics("US-NEW", prices, None)
    codes = {row["metric_code"] for row in rows}

    assert "total_return_1y" not in codes
    assert "total_return_since_inception" in codes
    assert (
        next(row for row in rows if row["metric_code"] == "total_return_since_inception")["period"]
        == "available"
    )
