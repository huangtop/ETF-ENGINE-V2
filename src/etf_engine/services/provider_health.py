from __future__ import annotations

from dataclasses import dataclass


RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "too many requests",
    "invalid crumb",
    "crumb is None",
)


def is_provider_limit_error(message: str) -> bool:
    normalized = message.casefold()
    return any(marker.casefold() in normalized for marker in RATE_LIMIT_MARKERS)


@dataclass
class ProviderCircuitBreaker:
    threshold: int = 2
    limit_failures: int = 0
    halted: bool = False

    def observe(self, messages: list[str]) -> bool:
        self.limit_failures += sum(is_provider_limit_error(message) for message in messages)
        self.halted = self.limit_failures >= self.threshold
        return self.halted

    @property
    def halt_reason(self) -> str | None:
        if not self.halted:
            return None
        return "provider_rate_limit_circuit_open"
