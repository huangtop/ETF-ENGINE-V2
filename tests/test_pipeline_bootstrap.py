import json
from types import SimpleNamespace

import pandas as pd

import etf_engine.pipeline as pipeline
import etf_engine.services.public_builder as public_builder
from etf_engine.models import ETFEntity
from etf_engine.services.holding_service import HoldingSyncResult


def entity(etf_id: str, market: str = "US") -> ETFEntity:
    ticker = etf_id.split("-", 1)[1]
    return ETFEntity(
        etf_id=etf_id,
        ticker=ticker,
        quote_symbol=ticker,
        name=ticker,
        listing_market=market,
        listing_exchange="TWSE" if market == "TW" else "US",
        currency="TWD" if market == "TW" else "USD",
        benchmark_symbol="0050.TW" if market == "TW" else "SPY",
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


def test_merge_metrics_preserves_unprocessed_etfs_and_replaces_current_value():
    previous = [
        {"etf_id": "US-SPY", "metric_code": "total_return_1y", "value": 10},
        {"etf_id": "TW-0050", "metric_code": "total_return_1y", "value": 20},
    ]
    current = [
        {"etf_id": "TW-0050", "metric_code": "total_return_1y", "value": 21}
    ]

    merged = pipeline._merge_metrics(previous, current)

    assert merged == [
        {"etf_id": "TW-0050", "metric_code": "total_return_1y", "value": 21},
        {"etf_id": "US-SPY", "metric_code": "total_return_1y", "value": 10},
    ]


def test_replace_metrics_removes_stale_codes_for_successfully_refreshed_etf():
    previous = [
        {"etf_id": "US-NEW", "metric_code": "total_return_1y", "value": 99},
        {"etf_id": "US-SPY", "metric_code": "total_return_1y", "value": 10},
    ]
    current = [
        {
            "etf_id": "US-NEW",
            "metric_code": "total_return_since_inception",
            "value": 5,
        }
    ]

    merged = pipeline._replace_metrics_for_etfs(previous, current, {"US-NEW"})

    assert merged == [
        {
            "etf_id": "US-NEW",
            "metric_code": "total_return_since_inception",
            "value": 5,
        },
        {"etf_id": "US-SPY", "metric_code": "total_return_1y", "value": 10},
    ]


def test_load_public_metrics_recovers_last_known_good(tmp_path, monkeypatch):
    selected = entity("US-SPY")
    public_path = tmp_path / "public" / "markets" / "US.json"
    public_path.parent.mkdir(parents=True)
    public_path.write_text(
        json.dumps(
            [
                {
                    "etf_id": "US-SPY",
                    "metrics": {
                        "total_return_1y": {"value": 17.6, "unit": "percent"},
                        "missing": {"value": None, "unit": "ratio"},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline,
        "settings",
        SimpleNamespace(public_dir=tmp_path / "public"),
    )

    assert pipeline._load_public_metrics([selected]) == [
        {
            "etf_id": "US-SPY",
            "metric_code": "total_return_1y",
            "value": 17.6,
            "unit": "percent",
        }
    ]


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
        public_dir=tmp_path / "public",
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


def test_all_market_bootstrap_splits_quota_between_tw_and_us(tmp_path, monkeypatch):
    entities = [
        entity("TW-A", "TW"),
        entity("TW-B", "TW"),
        entity("US-A"),
        entity("US-B"),
    ]

    class Seed:
        def entities(self):
            return entities

    prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )
    attempted = []

    class Prices:
        def sync(self, selected, _start, _end):
            attempted.append(selected.etf_id)
            return prices

    class Holdings:
        def sync_with_status(self, _selected):
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
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda *_args: [])
    monkeypatch.setattr(pipeline, "build_public", lambda: None)

    state = pipeline.run("all", bootstrap_limit=2)

    assert "TW-A" in attempted and "US-A" in attempted
    assert "TW-B" not in attempted and "US-B" not in attempted
    assert state["bootstrap_attempted"] == 2
    bootstrap = json.loads((fake_settings.state_dir / "bootstrap.json").read_text())
    assert bootstrap["cursor_by_market"] == {"TW": "TW-A", "US": "US-A"}


def test_bootstrap_only_skips_cached_entities_and_does_not_publish(tmp_path, monkeypatch):
    entities = [entity("TW-CACHED", "TW"), entity("TW-MISSING", "TW")]
    price_dir = tmp_path / "normalized" / "prices"
    price_dir.mkdir(parents=True)
    (price_dir / "TW-CACHED.parquet").touch()

    class Seed:
        def entities(self):
            return entities

    attempted = []

    class Prices:
        def sync(self, selected, _start, _end):
            attempted.append(selected.etf_id)
            return pd.DataFrame(
                {"adj_close": [100.0, 101.0]},
                index=pd.date_range("2026-07-28", periods=2),
            )

    class Holdings:
        def sync_with_status(self, _selected):
            return HoldingSyncResult(rows=[], fetched=False)

    fake_settings = SimpleNamespace(
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        public_dir=tmp_path / "public",
        ensure_dirs=lambda: (tmp_path / "state").mkdir(parents=True),
    )
    published = []
    monkeypatch.setattr(pipeline, "settings", fake_settings)
    monkeypatch.setattr(pipeline, "SeedRepository", Seed)
    monkeypatch.setattr(pipeline, "PriceService", Prices)
    monkeypatch.setattr(pipeline, "HoldingService", Holdings)
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda *_args: [])
    monkeypatch.setattr(pipeline, "build_public", lambda: published.append(True))

    state = pipeline.run(
        "TW",
        bootstrap_limit=1,
        bootstrap_only=True,
        publish=False,
    )

    assert attempted[0] == "TW-MISSING"
    assert "TW-CACHED" not in attempted
    assert state["processed"] == 1
    assert state["bootstrap_only"] is True
    assert state["published"] is False
    assert published == []


def test_benchmark_failure_keeps_price_metrics_and_holdings_independent(
    tmp_path, monkeypatch
):
    selected = entity("TW-TEST", "TW")

    class Seed:
        def entities(self):
            return [selected]

    prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )

    class Prices:
        def sync(self, target, _start, _end):
            if target.etf_id == "TW-BENCH":
                raise RuntimeError("benchmark unavailable")
            return prices

    holdings_attempted = []

    class Holdings:
        def sync_with_status(self, target):
            holdings_attempted.append(target.etf_id)
            return HoldingSyncResult(rows=[], fetched=False)

    metric_calls = []
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
    monkeypatch.setattr(
        pipeline,
        "calculate_metrics",
        lambda etf_id, _prices, benchmark: metric_calls.append((etf_id, benchmark)) or [],
    )
    monkeypatch.setattr(pipeline, "build_public", lambda: None)

    state = pipeline.run("TW", bootstrap_limit=0, publish=False)

    assert metric_calls == [("TW-TEST", None)]
    assert holdings_attempted == ["TW-TEST"]
    assert any(error["stage"] == "benchmark" for error in state["errors"])
    assert not any(error["stage"] == "prices" for error in state["errors"])


def test_pipeline_reports_holdings_provider_errors(tmp_path, monkeypatch):
    selected = entity("US-TEST")

    class Seed:
        def entities(self):
            return [selected]

    prices = pd.DataFrame(
        {"adj_close": [100.0, 101.0]},
        index=pd.date_range("2026-07-28", periods=2),
    )

    class Prices:
        def sync(self, _target, _start, _end):
            return prices

    class Holdings:
        def sync_with_status(self, _target):
            return HoldingSyncResult(
                rows=[],
                fetched=False,
                errors=("yahoo: rate limited",),
            )

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
    monkeypatch.setattr(pipeline, "calculate_metrics", lambda *_args: [])

    state = pipeline.run("US", bootstrap_limit=0, publish=False)

    assert any(
        error["stage"] == "holdings" and "rate limited" in error["error"]
        for error in state["errors"]
    )


def test_pipeline_stops_remaining_entities_after_repeated_provider_limits(
    tmp_path, monkeypatch
):
    entities = [entity(f"US-{ticker}") for ticker in ("A", "B", "C")]

    class Seed:
        def entities(self):
            return entities

    attempted = []

    class Prices:
        def sync(self, selected, _start, _end):
            attempted.append(selected.etf_id)
            raise RuntimeError("HTTP 429 too many requests")

    class Holdings:
        def sync_with_status(self, _selected):
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

    state = pipeline.run("US", bootstrap_limit=0, publish=False)

    assert attempted == ["US-A", "US-B"]
    assert state["provider_halted"]
    assert state["provider_halt_reason"] == "provider_rate_limit_circuit_open"
    assert state["skipped_after_provider_halt"] == ["US-C"]


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
        def __init__(self, **_kwargs):
            pass

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


def test_public_builder_preserves_last_known_good_when_cache_is_missing(
    tmp_path, monkeypatch
):
    entities = [entity("US-SPY")]

    class Seed:
        def entities(self):
            return entities

        def classifications(self):
            return []

    class Prices:
        def load(self, _etf_id):
            return pd.DataFrame()

    class Holdings:
        def load(self, _etf_id):
            return []

    class Exporter:
        def __init__(self, **_kwargs):
            pass

        def build(self):
            return {}

    fake_settings = SimpleNamespace(
        seed_dir=tmp_path / "seed",
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        public_dir=tmp_path / "public",
    )
    (fake_settings.normalized_dir / "metrics").mkdir(parents=True)
    fake_settings.state_dir.mkdir(parents=True)
    existing_path = fake_settings.public_dir / "etf" / "US-SPY.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return_1y": {"value": 17.6, "unit": "percent"}
                },
                "latest_price": {"date": "2026-07-28", "value": 740.86},
                "trend": [{"date": "2026-07-28", "value": 100}],
                "top_holdings": [
                    {
                        "holding_symbol": "NVDA",
                        "holding_name_en": "NVIDIA Corp",
                        "holding_name_zh": "輝達",
                        "display_name": "輝達",
                        "display_label": "(NVDA)輝達",
                        "bilingual_name": "NVIDIA Corp（輝達）",
                        "weight": 0.08,
                    }
                ],
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

    item = json.loads(existing_path.read_text())
    assert item["bootstrap_status"] == "ready"
    assert item["metrics"]["total_return_1y"]["value"] == 17.6
    assert item["latest_price"]["value"] == 740.86
    assert item["top_holdings"][0]["holding_symbol"] == "NVDA"


def test_public_builder_ignores_unconfirmed_holdings_cache(tmp_path, monkeypatch):
    entities = [entity("US-SPY")]

    class Seed:
        def entities(self):
            return entities

        def classifications(self):
            return []

    class Prices:
        def load(self, _etf_id):
            return pd.DataFrame()

    class Holdings:
        def load(self, _etf_id):
            return [
                {
                    "holding_symbol": "AMD",
                    "holding_name": "Advanced Micro Devices Inc",
                    "weight": 0.2,
                    "as_of": None,
                    "source": "yahoo",
                }
            ]

    class Exporter:
        def __init__(self, **_kwargs):
            pass

        def build(self):
            return {}

    fake_settings = SimpleNamespace(
        seed_dir=tmp_path / "seed",
        normalized_dir=tmp_path / "normalized",
        state_dir=tmp_path / "state",
        public_dir=tmp_path / "public",
    )
    fake_settings.state_dir.mkdir(parents=True)
    existing = {
        "etf_id": "US-SPY",
        "top_holdings": [
            {
                "holding_symbol": "NVDA",
                "holding_name_en": "NVIDIA Corp",
                "holding_name_zh": "輝達",
                "display_name": "輝達",
                "display_label": "(NVDA)輝達",
                "bilingual_name": "NVIDIA Corp（輝達）",
                "weight": 0.1,
                "source": "yahoo",
            }
        ],
    }
    existing_path = fake_settings.public_dir / "etf" / "US-SPY.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(public_builder, "settings", fake_settings)
    monkeypatch.setattr(public_builder, "SeedRepository", Seed)
    monkeypatch.setattr(public_builder, "PriceRepository", Prices)
    monkeypatch.setattr(public_builder, "HoldingService", Holdings)
    monkeypatch.setattr(public_builder, "HoldingsChangeExporter", Exporter)
    monkeypatch.setattr(public_builder, "load_translations", lambda: {})
    monkeypatch.setattr(public_builder, "load_holding_translations", lambda: {})

    public_builder.build_public()

    result = json.loads(existing_path.read_text())
    assert result["top_holdings"][0]["holding_symbol"] == "NVDA"
