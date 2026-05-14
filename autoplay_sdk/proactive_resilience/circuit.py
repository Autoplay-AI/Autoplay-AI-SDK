from __future__ import annotations

import time
from dataclasses import dataclass, field

from autoplay_sdk.proactive_resilience.config import CircuitBreakerConfig


@dataclass
class InMemoryProactiveCircuitBreaker:
    """In-process circuit + streak for unit tests (no network)."""

    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    fail_streak: int = 0
    circuit_open_until: float | None = None

    def is_open(self, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else float(now)
        if self.circuit_open_until is None:
            return False
        if t < self.circuit_open_until:
            return True
        self.circuit_open_until = None
        return False

    def record_success(self) -> None:
        self.fail_streak = 0
        self.circuit_open_until = None

    def record_failure_opening_if_needed(self, now: float | None = None) -> bool:
        """Increment streak; return True if the circuit is now open."""
        if self.config.disabled or self.config.failure_threshold <= 0:
            return False
        t = time.monotonic() if now is None else float(now)
        self.fail_streak += 1
        if self.fail_streak >= self.config.failure_threshold:
            self.circuit_open_until = t + max(0.0, float(self.config.pause_s))
            self.fail_streak = 0
            return True
        return False
