from types import SimpleNamespace

import pytest

from etf_engine.providers import twse


def test_twse_provider_paces_requests(monkeypatch):
    clock = iter([10.0, 10.05, 10.25])
    sleeps = []
    monkeypatch.setattr(twse.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(twse.time, "sleep", sleeps.append)
    monkeypatch.setattr(twse.random, "uniform", lambda _start, _end: 0.0)
    monkeypatch.setattr(
        twse.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            headers={},
            raise_for_status=lambda: None,
            json=lambda: {"data": []},
        ),
    )
    provider = twse.TWSEPriceProvider(request_interval=0.2, jitter=0)

    provider._month.__wrapped__(provider, "0050", "20260101")
    provider._month.__wrapped__(provider, "0050", "20260201")

    assert sleeps == [pytest.approx(0.15)]


def test_twse_provider_honors_bounded_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(twse.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(twse.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        twse.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=429,
            headers={"Retry-After": "120"},
            raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError("429")),
            json=lambda: {},
        ),
    )
    provider = twse.TWSEPriceProvider(request_interval=0, jitter=0)

    try:
        provider._month.__wrapped__(provider, "0050", "20260101")
    except RuntimeError:
        pass

    assert sleeps == [30.0]
