"""Unit tests for autoplay_sdk.proactive_resilience (pure helpers, no Redis)."""

from __future__ import annotations

import time

from autoplay_sdk.proactive_resilience import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    CircuitBreakerConfig,
    InMemoryProactiveCircuitBreaker,
    ProactiveDeliveryOutcome,
    ProactiveRateLimitConfig,
    ProactiveResilienceKeySpace,
    outcome_counts_toward_circuit,
    proactive_key_suffixes,
)


def test_default_min_interval_matches_plan() -> None:
    assert DEFAULT_MIN_INTERVAL_SECONDS == 300.0
    assert ProactiveRateLimitConfig().min_interval_seconds == 300.0


def test_key_space_stable_suffixes() -> None:
    ks = ProactiveResilienceKeySpace(surface="intercom", product_id="prod-a")
    assert "v1:intercom:prod-a:circuit_open" == ks.circuit_open_key()
    assert "v1:intercom:prod-a:min_interval:sess1" == ks.min_interval_key("sess1")


def test_proactive_key_suffixes_map() -> None:
    m = proactive_key_suffixes(surface="slack", product_id="p1", session_id="s1")
    assert m["circuit_open"].endswith(":circuit_open")
    assert ":min_interval:s1" in m["min_interval"]


def test_outcome_counts_toward_circuit() -> None:
    assert outcome_counts_toward_circuit(ProactiveDeliveryOutcome.TRANSPORT_ERROR)
    assert outcome_counts_toward_circuit(ProactiveDeliveryOutcome.RATE_LIMITED)
    assert not outcome_counts_toward_circuit(ProactiveDeliveryOutcome.SUCCESS)
    assert not outcome_counts_toward_circuit(ProactiveDeliveryOutcome.VALIDATION_ERROR)


def test_in_memory_circuit_opens_after_threshold() -> None:
    cb = InMemoryProactiveCircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=2, pause_s=10.0)
    )
    t0 = 1000.0
    assert not cb.record_failure_opening_if_needed(now=t0)
    assert cb.record_failure_opening_if_needed(now=t0 + 0.01)
    assert cb.is_open(now=t0 + 1)


def test_in_memory_circuit_success_resets() -> None:
    cb = InMemoryProactiveCircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=5, pause_s=10.0)
    )
    cb.fail_streak = 3
    cb.record_success()
    assert cb.fail_streak == 0


def test_in_memory_circuit_disabled_never_opens() -> None:
    cb = InMemoryProactiveCircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=1, pause_s=10.0, disabled=True)
    )
    assert not cb.record_failure_opening_if_needed(now=time.monotonic())
