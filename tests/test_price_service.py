from datetime import date

import pandas as pd
import pytest

from etf_engine.models import ETFEntity
from etf_engine.repository import PriceRepository
from etf_engine.services.price_service import PriceService


def entity():
    return ETFEntity(
        etf_id="US-SPY",
        ticker="SPY",
        quote_symbol="SPY",
        name="SPY",
        listing_market="US",
        listing_exchange="US",
        currency="USD",
        benchmark_symbol="SPY",
    )


class MemoryRepository:
    def __init__(self, frame):
        self.frame = frame
        self.saved = None

    def load(self, _etf_id):
        return self.frame

    def save(self, _etf_id, frame):
        self.saved = frame
        self.frame = frame


class Provider:
    name = "test"

    def __init__(self, frame=None, error=None):
        self.frame = frame if frame is not None else pd.DataFrame()
        self.error = error
        self.requested_start = None

    def supports(self, _entity):
        return True

    def fetch(self, _entity, start, _end):
        self.requested_start = start
        if self.error:
            raise self.error
        return self.frame


def frame(dates, values):
    return pd.DataFrame(
        {"close": values, "adj_close": values},
        index=pd.to_datetime(dates),
    )


def test_refresh_uses_overlap_and_repairs_recent_missing_day():
    existing = frame(["2026-07-01", "2026-07-03"], [100.0, 103.0])
    fresh = frame(["2026-07-02", "2026-07-03", "2026-07-06"], [102.0, 103.5, 106.0])
    repo = MemoryRepository(existing)
    provider = Provider(fresh)
    service = PriceService(repo=repo, providers=[provider])

    result = service.sync(entity(), date(2026, 1, 1), date(2026, 7, 6))

    assert provider.requested_start == date(2026, 6, 3)
    assert list(result.index.strftime("%Y-%m-%d")) == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
    ]
    assert result.loc["2026-07-03", "close"] == 103.5


@pytest.mark.parametrize("provider", [Provider(), Provider(error=RuntimeError("limited"))])
def test_empty_or_failed_provider_preserves_existing_cache(provider):
    existing = frame(["2026-07-01"], [100.0])
    repo = MemoryRepository(existing)
    service = PriceService(repo=repo, providers=[provider])

    result = service.sync(entity(), date(2026, 1, 1), date(2026, 7, 2))

    assert repo.saved is None
    pd.testing.assert_frame_equal(result, existing)


def test_atomic_repository_failure_preserves_existing_file(tmp_path, monkeypatch):
    repository = PriceRepository()
    monkeypatch.setattr(repository, "path", lambda _etf_id: tmp_path / "US-SPY.parquet")
    original = frame(["2026-07-01"], [100.0])
    replacement = frame(["2026-07-01", "2026-07-02"], [100.0, 101.0])
    original.to_parquet(repository.path("US-SPY"))

    import etf_engine.repository as repository_module

    monkeypatch.setattr(
        repository_module.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        repository.save("US-SPY", replacement)

    pd.testing.assert_frame_equal(pd.read_parquet(repository.path("US-SPY")), original)
    assert not list(tmp_path.glob("*.tmp"))
