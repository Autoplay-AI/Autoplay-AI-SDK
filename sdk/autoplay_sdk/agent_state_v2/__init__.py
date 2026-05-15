"""Agent state v2 — 3-state session FSM (THINKING / PROACTIVE / REACTIVE).

Coexists with ``autoplay_sdk.agent_states`` (5-state ``AgentStateMachine``);
nothing in that module is changed.

Typical usage::

    from autoplay_sdk.agent_state_v2 import SessionState, AgentStateV2

    session = SessionState()
    ok = session.transition_to_proactive("my_trigger")
    session.tick()
"""

from autoplay_sdk.agent_state_v2.session_state import (
    ProactiveState,
    ReactiveState,
    SessionState,
    ThinkingState,
)
from autoplay_sdk.agent_state_v2.types import AgentStateV2, InvalidTransitionError

__all__ = [
    "AgentStateV2",
    "InvalidTransitionError",
    "ProactiveState",
    "ReactiveState",
    "SessionState",
    "ThinkingState",
]
