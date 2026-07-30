import json
from datetime import datetime, timezone

import pytest

import etf_engine.services.holding_service as holding_service_module
from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import normalize
from etf_engine.services.holding_service import HoldingService
from etf_engine.services.holdings_history import HoldingsHistoryService


def clock(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def holdings(weight=0.125):
    return [
        {
            "etf_id": "US-TEST",
            "holding_symbol": "NVDA",
            "weight": weight,
            "source": "yahoo",
            "as_of": None,
        }
    ]


def test_creates_snapshot_manifest_index_and_observation(tmp_path):
    history = HoldingsHistoryService(
        tmp_path,
        clock([datetime(2026, 7, 30, 1, tzinfo=timezone.utc)][0]),
    )
    result = history.record("US-TEST", holdings())

    snapshot = json.loads((tmp_path / "snapshots" / f"{result['snapshot_id']}.json").read_text())
    assert snapshot["observed_at"] == "2026-07-30T01:00:00Z"
    assert snapshot["provider_generated_at"] is None
    assert snapshot["provider_as_of"] is None
    assert snapshot["provider_as_of_status"] == "unavailable"
    assert snapshot["coverage"] == "top_holdings_only"
    assert snapshot["holdings"] == [
        {
            "etf_id": "US-TEST",
            "holding_symbol": "NVDA",
            "weight": 0.125,
            "source": "yahoo",
        }
    ]
    assert len(snapshot["content_sha256"]) == 64

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    index = json.loads((tmp_path / "snapshot_index.json").read_text())
    observations = json.loads((tmp_path / "observations.json").read_text())
    assert manifest["snapshot_count"] == 1
    assert manifest["observation_count"] == 1
    assert index["etfs"]["US-TEST"]["current"] == result["snapshot_id"]
    assert index["etfs"]["US-TEST"]["previous"] is None
    assert observations["observations"][0]["content_changed"] is True


def test_same_content_adds_observation_without_duplicate_snapshot(tmp_path):
    history = HoldingsHistoryService(
        tmp_path,
        clock(
            datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 31, 1, tzinfo=timezone.utc),
        ),
    )
    first = history.record("US-TEST", holdings())
    second = history.record("US-TEST", holdings())

    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["snapshot_created"] is False
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1
    observations = json.loads((tmp_path / "observations.json").read_text())
    assert len(observations["observations"]) == 2
    assert observations["observations"][1]["content_changed"] is False


def test_changed_content_moves_current_to_previous(tmp_path):
    history = HoldingsHistoryService(
        tmp_path,
        clock(
            datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 31, 1, tzinfo=timezone.utc),
        ),
    )
    first = history.record("US-TEST", holdings(0.125))
    second = history.record("US-TEST", holdings(0.15))
    entry = json.loads((tmp_path / "snapshot_index.json").read_text())["etfs"]["US-TEST"]
    assert entry["current"] == second["snapshot_id"]
    assert entry["previous"] == first["snapshot_id"]
    assert len(entry["snapshots"]) == 2


def test_empty_snapshot_is_rejected_without_files(tmp_path):
    history = HoldingsHistoryService(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        history.record("US-TEST", [])
    assert list(tmp_path.iterdir()) == []


def test_normalize_does_not_invent_provider_as_of():
    rows = normalize("US-TEST", [{"symbol": "NVDA", "weight": 0.1}], "yahoo")
    assert rows[0]["as_of"] is None

    missing_date = normalize(
        "US-TEST", [{"symbol": "NVDA", "weight": 0.1, "as_of": float("nan")}], "yahoo"
    )
    assert missing_date[0]["as_of"] is None


def test_provider_as_of_is_distinct_from_observed_at(tmp_path):
    history = HoldingsHistoryService(
        tmp_path,
        lambda: datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
    )
    result = history.record(
        "US-TEST",
        holdings(),
        provider_generated_at="2026-07-29T20:00:00Z",
        provider_as_of="2026-07-28",
    )
    snapshot = json.loads((tmp_path / "snapshots" / f"{result['snapshot_id']}.json").read_text())
    assert snapshot["observed_at"] == "2026-07-30T01:00:00Z"
    assert snapshot["provider_generated_at"] == "2026-07-29T20:00:00Z"
    assert snapshot["provider_as_of"] == "2026-07-28"
    assert snapshot["provider_as_of_status"] == "available"


class Provider:
    name = "yahoo"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def fetch(self, entity):
        if self.error:
            raise self.error
        return self.result


class HistorySpy:
    def __init__(self):
        self.calls = []

    def record(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def entity():
    return ETFEntity(
        etf_id="US-TEST",
        ticker="TEST",
        quote_symbol="TEST",
        name="Test ETF",
        listing_market="US",
        listing_exchange="NYSE",
        currency="USD",
        benchmark_symbol="SPY",
    )


def test_provider_failure_preserves_last_known_good_and_does_not_record(tmp_path, monkeypatch):
    spy = HistorySpy()
    service = HoldingService(providers=[Provider(error=RuntimeError("provider down"))], history=spy)
    cache = tmp_path / "US-TEST.json"
    cache.write_text(json.dumps(holdings()), encoding="utf-8")
    monkeypatch.setattr(service, "path", lambda etf_id: cache)

    result = service.sync_with_status(entity())

    assert result.fetched is False
    assert result.rows == holdings()
    assert spy.calls == []
    assert json.loads(cache.read_text()) == holdings()


def test_success_records_history_and_updates_cache(tmp_path, monkeypatch):
    spy = HistorySpy()
    fresh = holdings(0.2)
    service = HoldingService(providers=[Provider(result=fresh)], history=spy)
    cache = tmp_path / "US-TEST.json"
    monkeypatch.setattr(service, "path", lambda etf_id: cache)

    result = service.sync_with_status(entity())

    assert result.fetched is True
    assert json.loads(cache.read_text()) == fresh
    assert spy.calls[0][0] == ("US-TEST", fresh)


def test_cache_replace_failure_preserves_last_known_good_and_skips_history(tmp_path, monkeypatch):
    spy = HistorySpy()
    old = holdings(0.1)
    fresh = holdings(0.2)
    service = HoldingService(providers=[Provider(result=fresh)], history=spy)
    cache = tmp_path / "US-TEST.json"
    cache.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(service, "path", lambda etf_id: cache)

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(holding_service_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failure"):
        service.sync_with_status(entity())

    assert json.loads(cache.read_text()) == old
    assert spy.calls == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_same_content_preserves_provider_metadata(tmp_path, monkeypatch):
    old = holdings(0.1)
    old[0]["holding_name"] = "NVIDIA Corp"
    old[0]["as_of"] = "2026-07-19"
    fresh = holdings(0.1)
    fresh[0]["holding_name"] = None
    fresh[0]["as_of"] = None
    spy = HistorySpy()
    service = HoldingService(providers=[Provider(result=fresh)], history=spy)
    cache = tmp_path / "US-TEST.json"
    cache.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(service, "path", lambda _etf_id: cache)

    result = service.sync_with_status(entity())

    assert result.rows[0]["holding_name"] == "NVIDIA Corp"
    assert result.rows[0]["as_of"] == "2026-07-19"


def test_changed_weight_does_not_reuse_old_provider_date(tmp_path, monkeypatch):
    old = holdings(0.1)
    old[0]["as_of"] = "2026-07-19"
    fresh = holdings(0.2)
    fresh[0]["as_of"] = None
    service = HoldingService(providers=[Provider(result=fresh)], history=HistorySpy())
    cache = tmp_path / "US-TEST.json"
    cache.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(service, "path", lambda _etf_id: cache)

    result = service.sync_with_status(entity())

    assert result.rows[0]["as_of"] is None
