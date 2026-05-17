"""Legacy five-state FSM public surface."""

from autoplay_sdk.agent_state.v1.state_machine import (
    AgentStateMachine,
    proactive_idle_eligible,
)
from autoplay_sdk.agent_state.v1.types import (
    AgentState,
    InvalidSnapshotError,
    InvalidTransitionError,
    ProactiveIdleExpiryResult,
    SessionMetrics,
    TaskProgress,
)
from autoplay_sdk.proactive.state.idle_expiry import (
    ProactiveIdleExpiryHooks,
    ProactiveIdleExpiryPipelineResult,
    ProactiveIdleExpiryPipelineStatus,
    run_proactive_idle_expiry,
)

__all__ = [
    "AgentState",
    "AgentStateMachine",
    "InvalidSnapshotError",
    "InvalidTransitionError",
    "ProactiveIdleExpiryHooks",
    "ProactiveIdleExpiryPipelineResult",
    "ProactiveIdleExpiryPipelineStatus",
    "ProactiveIdleExpiryResult",
    "SessionMetrics",
    "TaskProgress",
    "proactive_idle_eligible",
    "run_proactive_idle_expiry",
]
