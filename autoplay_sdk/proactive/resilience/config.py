from __future__ import annotations

from dataclasses import dataclass, field

# Product default: at most one proactive suggestion per 5 minutes per
# (product, session, surface) — override via host env e.g. PROACTIVE_MIN_INTERVAL_SECONDS.
DEFAULT_MIN_INTERVAL_SECONDS: float = 300.0


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """When consecutive transport-class failures reach ``failure_threshold``, open circuit."""

    failure_threshold: int = 5
    pause_s: float = 120.0
    # ``0`` disables circuit breaker behavior (always closed unless externally forced).
    disabled: bool = False


@dataclass(frozen=True, slots=True)
class ProactiveRateLimitConfig:
    """Rate and spacing knobs for proactive deliveries.

    ``0`` disables the corresponding guard where documented.
    """

    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    max_attempts_per_product_per_minute: int = 0
    max_per_session_per_hour: int = 0
    max_per_user_per_day: int = 0


@dataclass(frozen=True, slots=True)
class ProactiveResilienceConfig:
    """Bundled proactive resilience settings for a host process."""

    surface_id: str = "intercom"
    circuit: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    rates: ProactiveRateLimitConfig = field(default_factory=ProactiveRateLimitConfig)
