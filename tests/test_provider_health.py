from etf_engine.services.provider_health import (
    ProviderCircuitBreaker,
    is_provider_limit_error,
)


def test_recognizes_provider_rate_limit_errors_without_treating_empty_as_limit():
    assert is_provider_limit_error("HTTP Error 429: Too Many Requests")
    assert is_provider_limit_error("Yahoo invalid crumb")
    assert not is_provider_limit_error("no provider data")
    assert not is_provider_limit_error("operation timed out")


def test_circuit_breaker_halts_after_repeated_limit_signals():
    breaker = ProviderCircuitBreaker(threshold=2)

    assert not breaker.observe(["HTTP 429"])
    assert breaker.observe(["too many requests"])
    assert breaker.halt_reason == "provider_rate_limit_circuit_open"
