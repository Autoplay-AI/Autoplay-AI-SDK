"""Enums and exceptions for agent state v2 (3-state session FSM)."""

from __future__ import annotations

from enum import Enum


class AgentStateV2(str, Enum):
    """Three operational states for the v2 session FSM.

    Named ``AgentStateV2`` to avoid collision with the existing
    ``autoplay_sdk.agent_states.AgentState`` (5-state enum).
    """

    THINKING = "thinking"
    PROACTIVE = "proactive_assistance"
    REACTIVE = "reactive_assistance"


class InvalidTransitionError(ValueError):
    """Raised when a requested state transition violates the allowed rules.

    Valid transitions::

        thinking  → proactive   (blocked if cooldown_active)
        thinking  → reactive    (cooldown does NOT block)
        proactive → thinking    ONLY via tick() timeout — never direct
        reactive  → thinking    ONLY via tick() timeout — never direct

    Direct proactive ↔ reactive transitions are never allowed.
    """
