"""Surface-agnostic proactive delivery resilience: key space, config, outcomes, test doubles.

Hosts (e.g. the event connector) implement persistence (Redis) using
:func:`proactive_key_suffixes` / :class:`ProactiveResilienceKeySpace` for stable keys.
The SDK does not import Redis or HTTP clients.
"""

from autoplay_sdk.proactive_resilience.circuit import InMemoryProactiveCircuitBreaker
from autoplay_sdk.proactive_resilience.config import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    CircuitBreakerConfig,
    ProactiveRateLimitConfig,
    ProactiveResilienceConfig,
)
from autoplay_sdk.proactive_resilience.keys import (
    ProactiveResilienceKeySpace,
    ProactiveSurfaceId,
    proactive_key_namespace,
    proactive_key_suffixes,
)
from autoplay_sdk.proactive_resilience.outcomes import (
    ProactiveDeliveryOutcome,
    outcome_counts_toward_circuit,
)
from autoplay_sdk.proactive_resilience.protocol import ProactiveResilienceStore

__all__ = [
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "CircuitBreakerConfig",
    "ProactiveResilienceConfig",
    "ProactiveRateLimitConfig",
    "ProactiveSurfaceId",
    "ProactiveResilienceKeySpace",
    "proactive_key_namespace",
    "proactive_key_suffixes",
    "ProactiveDeliveryOutcome",
    "outcome_counts_toward_circuit",
    "InMemoryProactiveCircuitBreaker",
    "ProactiveResilienceStore",
]
