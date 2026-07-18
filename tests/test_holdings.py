from etf_engine.services.holding_service import overlap


def test_weighted_overlap():
    left = [
        {"holding_symbol": "NVDA", "weight": 0.20},
        {"holding_symbol": "MSFT", "weight": 0.10},
    ]
    right = [
        {"holding_symbol": "NVDA", "weight": 0.12},
        {"holding_symbol": "AVGO", "weight": 0.08},
    ]
    result = overlap(left, right)
    assert result["shared_holdings_count"] == 1
    assert result["overlap_ratio"] == 0.12
