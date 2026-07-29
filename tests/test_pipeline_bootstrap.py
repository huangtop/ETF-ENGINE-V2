import json
from types import SimpleNamespace

import pandas as pd

import etf_engine.pipeline as pipeline
import etf_engine.services.public_builder as public_builder
from etf_engine.models import ETFEntity
from etf_engine.services.holding_service import HoldingSyncResult


def entity(etf_id: str) -> ETFEntity:
    ticker = etf_id.split("-", 1)[1]
    return ETFEntity(
        etf_id=etf_id,
        ticker=ticker,
        quote_symbol=ticker,
        name=ticker,
        listing_market="US",
        listing_exchange="US",
        currency="USD",
        benchmark_symbol="SPY",
    )


def test_selects_all_cached_and_round_robin_missing():
    entities = [entity(f"US-{ticker}") for ticker in ("A", "B", "C", "D")]
    scheduled, attempted, cursor = pipeline.select_entities_for_run(
        entities,
        {"US-A", "US-C"},
        bootstrap_limit=1,
        cursor="US-B",
    )
    assert [row.etf_id for row in scheduled] == ["US-A", "US-C", "US-D"]
    assert [row.etf_id for row in attempted] == ["US-D"]
    assert cursor == "US-D"

    _, attempted, cursor = pipeline.select_entities_for_run(
        entities,
        {"US-A", "US-C"},
        bootstrap_limit=1,
        cursor=cursor,
    )
    assert [row.etf_id for row in attempted] == ["US-B"]
    assert cursor == "US-B"


def test_pipeline_bounds_uncached_entities_and_records_pending(tmp_path, monkeypatch):
    entities = [entity(f"US-{ticker}") for ticker in ("A", "B", "C")]
    price_dir = tmp_path / "normalized" / "prices"
    price_dir.mkdir(parents=True)
    (price_dir / "US-A.parquet").touch()

    class Seed:
        def entities(self):
            return entities

    prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )

    class Prices:
        def sync(self, _entity, _start, _end):
            return prices

    holdings_attempted = []

    class Holdings:
        def sync_with_status(self, selected):
            holdings_attempted.append(selected.etf_id)
            return HoldingSyncResult(rows=[], fetched=False)

    fake_settings = SimpleNamespace(
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        ensure_dirs=lambda: (tmp_path / "state").mkdir(parents=True),
    )
    monkeypatch.setattr(pipeline, "settings", fake_settings)
    monkeypatch.setattr(pipeline, "SeedRepository", Seed)
    monkeypatch.setattr(pipeline, "PriceService", Prices)
    monkeypatch.setattr(pipeline, "HoldingService", Holdings)
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda *_args: [])
    monkeypatch.setattr(pipeline, "build_public", lambda: None)

    state = pipeline.run("US", bootstrap_limit=1)

    assert holdings_attempted == ["US-A", "US-B"]
    assert state["eligible"] == 3
    assert state["processed"] == 2
    assert state["bootstrap_attempted"] == 1
    assert state["bootstrap_ready"] == 1
    assert state["bootstrap_pending"] == 2


def test_public_builder_exposes_ready_pending_and_failed(tmp_path, monkeypatch):
    entities = [entity(f"US-{ticker}") for ticker in ("READY", "PENDING", "FAILED")]

    class Seed:
        def entities(self):
            return entities

        def classifications(self):
            return []

    ready_prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )

    class Prices:
        def load(self, etf_id):
            return ready_prices if etf_id == "US-READY" else pd.DataFrame()

    class Holdings:
        def load(self, _etf_id):
            return []

    class Exporter:
        def build(self):
            return {}

    fake_settings = SimpleNamespace(
        seed_dir=tmp_path / "seed",
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        public_dir=tmp_path / "public",
    )
    fake_settings.state_dir.mkdir(parents=True)
    (fake_settings.state_dir / "last_run.json").write_text(
        json.dumps(
            {
                "errors": [
                    {
                        "etf_id": "US-FAILED",
                        "stage": "prices",
                        "error": "provider failed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(public_builder, "settings", fake_settings)
    monkeypatch.setattr(public_builder, "SeedRepository", Seed)
    monkeypatch.setattr(public_builder, "PriceRepository", Prices)
    monkeypatch.setattr(public_builder, "HoldingService", Holdings)
    monkeypatch.setattr(public_builder, "HoldingsChangeExporter", Exporter)
    monkeypatch.setattr(public_builder, "load_translations", lambda: {})
    monkeypatch.setattr(public_builder, "load_holding_translations", lambda: {})

    public_builder.build_public()

    payload = json.loads((fake_settings.public_dir / "etfs.json").read_text())
    statuses = {row["etf_id"]: row["bootstrap_status"] for row in payload}
    manifest = json.loads((fake_settings.public_dir / "manifest.json").read_text())
    assert statuses == {
        "US-READY": "ready",
        "US-PENDING": "pending",
        "US-FAILED": "failed",
    }
    assert manifest["bootstrap"] == {"ready": 1, "pending": 1, "failed": 1}
