import pandas as pd

import json

from etf_engine.services.public_builder import (
    _market_summary,
    _price_metadata,
    _write_api_manifest,
    write_json,
)


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


def test_market_summary_keeps_ranking_fields_and_omits_heavy_detail():
    item = {
        "etf_id": "TW-0050",
        "ticker": "0050",
        "listing_market": "TW",
        "display_name": "元大台灣50",
        "classifications": [{"dimension": "strategy", "code": "broad_market"}],
        "metrics": {"total_return_1y": {"value": 12.3, "unit": "percent"}},
        "latest_price": {"date": "2026-08-11", "value": 60.0, "currency": "TWD"},
        "trend": [
            {"date": "2026-07-11", "value": 100},
            {"date": "2026-08-11", "value": 110},
        ],
        "top_holdings": [{"holding_symbol": "2330.TW", "weight": 0.5}],
        "research": {"tier": "core"},
    }

    summary = _market_summary(item)

    assert summary["etf_id"] == "TW-0050"
    assert summary["metrics"]["total_return_1y"] == item["metrics"]["total_return_1y"]
    assert summary["metrics"]["total_return_1m"]["value"] == 10.0
    assert "trend" not in summary
    assert "top_holdings" not in summary
    assert "research" not in summary


def test_api_manifest_versions_summary_detail_and_history_by_content(tmp_path):
    write_json(tmp_path / "summaries" / "TW.json", [{"etf_id": "TW-0050"}])
    write_json(tmp_path / "summaries" / "US.json", [])
    write_json(tmp_path / "etf" / "TW-0050.json", {"etf_id": "TW-0050"})
    write_json(
        tmp_path / "history" / "holdings" / "TW-0050.json",
        {"etf_id": "TW-0050", "transitions": []},
    )

    _write_api_manifest(
        tmp_path,
        "2026-08-12T00:00:00+00:00",
        [{"etf_id": "TW-0050"}],
    )
    manifest = json.loads((tmp_path / "api_manifest.json").read_text())

    assert manifest["cache_strategy"] == "content_sha256"
    assert manifest["market_summaries"]["TW"]["bytes"] > 0
    assert len(manifest["etf_details"]["TW-0050"]["content_sha256"]) == 64
    assert manifest["holdings_history"]["TW-0050"]["path"].endswith(
        "TW-0050.json"
    )
