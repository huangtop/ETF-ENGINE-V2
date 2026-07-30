from types import SimpleNamespace

import pandas as pd
import pytest

import etf_engine.pipeline as pipeline
from etf_engine.models import ETFEntity
from etf_engine.services.holding_service import HoldingSyncResult


@pytest.mark.parametrize("price_error", [False, True])
def test_pipeline_attempts_holdings_sync_for_tw_etfs_even_when_prices_fail(
    tmp_path, monkeypatch, price_error
):
    tw_etf = ETFEntity(
        etf_id="TW-TEST",
        ticker="TEST",
        quote_symbol="TEST.TW",
        name="Test TW ETF",
        listing_market="TW",
        listing_exchange="TWSE",
        currency="TWD",
        benchmark_symbol="^TWII",
    )

    class Seed:
        def entities(self):
            return [tw_etf]

    prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )

    class Prices:
        def sync(self, entity, start, end):
            if price_error:
                raise RuntimeError("price provider failed")
            return prices

    synced = []

    class Holdings:
        def sync_with_status(self, entity):
            synced.append(entity.etf_id)
            return HoldingSyncResult(rows=[], fetched=False)

    fake_settings = SimpleNamespace(
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        public_dir=tmp_path / "public",
        ensure_dirs=lambda: (tmp_path / "state").mkdir(parents=True),
    )
    monkeypatch.setattr(pipeline, "settings", fake_settings)
    monkeypatch.setattr(pipeline, "SeedRepository", Seed)
    monkeypatch.setattr(pipeline, "PriceService", Prices)
    monkeypatch.setattr(pipeline, "HoldingService", Holdings)
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda *args: [])
    monkeypatch.setattr(pipeline, "build_public", lambda: None)

    state = pipeline.run("TW")

    assert synced == ["TW-TEST"]
    assert bool(state["errors"]) is price_error
