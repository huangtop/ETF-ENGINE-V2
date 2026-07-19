from etf_engine.providers.holdings import normalize
from etf_engine.services.holding_service import overlap


def test_normalize_percent_weights():
    rows = normalize(
        "US-TEST",
        [{"symbol": "AAA", "weight": "12.5%"}],
        "test",
    )
    assert rows[0]["holding_symbol"] == "AAA"
    assert rows[0]["weight"] == 0.125


def test_overlap_uses_minimum_weight():
    left = [{"holding_symbol": "AAA", "weight": 0.20}]
    right = [{"holding_symbol": "AAA", "weight": 0.10}]
    result = overlap(left, right)
    assert result["overlap_ratio"] == 0.10
