"""Orchestrate proactive idle teardown for chat integrations (remote delete → FSM → local cleanup)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from autoplay_sdk.agent_state.v2.session_state import SessionState
from autoplay_sdk.agent_state.v2.types import AgentStateV2

logger = logging.getLogger(__name__)


class ProactiveIdleExpiryPipelineStatus(str, Enum):
    """Outcome of :func:`run_proactive_idle_expiry`."""

    SKIPPED_NOT_ELIGIBLE = "skipped_not_eligible"
    REMOTE_DELETE_FAILED = "remote_delete_failed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ProactiveIdleExpiryPipelineResult:
    """Structured result from :func:`run_proactive_idle_expiry`."""

    status: ProactiveIdleExpiryPipelineStatus
    fsm_result: ProactiveIdleExpiryResult | None = None


@dataclass(frozen=True)
class ProactiveIdleExpiryResult:
    """Outcome of proactive idle transition attempt for v2 session state."""

    transitioned: bool
    reset_chat_thread_binding: bool = False

    def __bool__(self) -> bool:
        return self.transitioned


@runtime_checkable
class ProactiveIdleExpiryHooks(Protocol):
    """Host hooks for remote thread deletion and local connector cleanup."""

    async def delete_remote_chat_thread(self) -> bool:
        """Return ``True`` only when remote teardown succeeded (proceed to FSM + local cleanup)."""

    async def clear_local_chat_thread_state(self) -> None:
        """Clear session↔thread binding and persisted FSM for this thread."""


async def run_proactive_idle_expiry(
    sm: SessionState,
    *,
    now: float,
    interaction_timeout_s: float,
    hooks: ProactiveIdleExpiryHooks,
) -> ProactiveIdleExpiryPipelineResult:
    """Run ordered pipeline: eligibility → remote delete → FSM idle expiry → local cleanup.

    Does not mutate the FSM when not eligible or when ``delete_remote_chat_thread`` returns
    ``False``.
    """
    if sm.current_state != AgentStateV2.PROACTIVE:
        return ProactiveIdleExpiryPipelineResult(
            status=ProactiveIdleExpiryPipelineStatus.SKIPPED_NOT_ELIGIBLE,
        )

    if now - sm.last_interaction_at < interaction_timeout_s:
        return ProactiveIdleExpiryPipelineResult(
            status=ProactiveIdleExpiryPipelineStatus.SKIPPED_NOT_ELIGIBLE,
        )

    if not await hooks.delete_remote_chat_thread():
        return ProactiveIdleExpiryPipelineResult(
            status=ProactiveIdleExpiryPipelineStatus.REMOTE_DELETE_FAILED,
        )

    current_state = sm.current_state
    original_timeout = sm.interaction_timeout_s
    try:
        sm.interaction_timeout_s = interaction_timeout_s
        sm.tick()
    finally:
        sm.interaction_timeout_s = original_timeout

    transitioned = (
        current_state == AgentStateV2.PROACTIVE
        and sm.current_state == AgentStateV2.THINKING
    )
    fsm_result = ProactiveIdleExpiryResult(
        transitioned=transitioned,
        reset_chat_thread_binding=transitioned,
    )
    if not fsm_result.transitioned:
        logger.error(
            "agent_states: proactive_idle_expiry FSM did not transition after successful "
            "remote delete (unexpected); proceeding with clear_local_chat_thread_state "
            "from_state=%s",
            sm.current_state.value,
            extra={
                "event_type": "proactive_idle_expiry_fsm_invariant",
                "from_state": sm.current_state.value,
            },
        )

    await hooks.clear_local_chat_thread_state()
    return ProactiveIdleExpiryPipelineResult(
        status=ProactiveIdleExpiryPipelineStatus.COMPLETED,
        fsm_result=fsm_result,
    )
