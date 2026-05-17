from __future__ import annotations

from enum import Enum


class ProactiveDeliveryOutcome(str, Enum):
    """Normalized result of a proactive transport attempt (Intercom, Slack, …)."""

    SUCCESS = "success"
    TRANSPORT_ERROR = "transport_error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    VALIDATION_ERROR = "validation_error"


def outcome_counts_toward_circuit(outcome: ProactiveDeliveryOutcome) -> bool:
    """True when this outcome should increment the host's failure streak."""
    return outcome in (
        ProactiveDeliveryOutcome.TRANSPORT_ERROR,
        ProactiveDeliveryOutcome.RATE_LIMITED,
        ProactiveDeliveryOutcome.TIMEOUT,
    )
