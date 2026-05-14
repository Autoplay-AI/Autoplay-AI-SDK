"""Orchestrate proactive idle teardown for chat integrations (remote delete → FSM → local cleanup)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from autoplay_sdk.agent_states.state_machine import (
    AgentStateMachine,
    proactive_idle_eligible,
)
from autoplay_sdk.agent_states.types import ProactiveIdleExpiryResult

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


@runtime_checkable
class ProactiveIdleExpiryHooks(Protocol):
    """Host hooks for remote thread deletion and local connector cleanup."""

    async def delete_remote_chat_thread(self) -> bool:
        """Return ``True`` only when remote teardown succeeded (proceed to FSM + local cleanup)."""

    async def clear_local_chat_thread_state(self) -> None:
        """Clear session↔thread binding and persisted FSM for this thread."""


async def run_proactive_idle_expiry(
    sm: AgentStateMachine,
    *,
    now: float,
    interaction_timeout_s: float,
    hooks: ProactiveIdleExpiryHooks,
) -> ProactiveIdleExpiryPipelineResult:
    """Run ordered pipeline: eligibility → remote delete → FSM idle expiry → local cleanup.

    Does not mutate the FSM when not eligible or when ``delete_remote_chat_thread`` returns
    ``False``.
    """
    if not proactive_idle_eligible(sm, now, interaction_timeout_s):
        return ProactiveIdleExpiryPipelineResult(
            status=ProactiveIdleExpiryPipelineStatus.SKIPPED_NOT_ELIGIBLE,
        )

    if not await hooks.delete_remote_chat_thread():
        return ProactiveIdleExpiryPipelineResult(
            status=ProactiveIdleExpiryPipelineStatus.REMOTE_DELETE_FAILED,
        )

    fsm_result = sm.expire_proactive_to_thinking_if_idle(now, interaction_timeout_s)
    if not fsm_result.transitioned:
        logger.error(
            "agent_states: proactive_idle_expiry FSM did not transition after successful "
            "remote delete (unexpected); proceeding with clear_local_chat_thread_state "
            "from_state=%s",
            sm.state.value,
            extra={
                "event_type": "proactive_idle_expiry_fsm_invariant",
                "from_state": sm.state.value,
            },
        )

    await hooks.clear_local_chat_thread_state()
    return ProactiveIdleExpiryPipelineResult(
        status=ProactiveIdleExpiryPipelineStatus.COMPLETED,
        fsm_result=fsm_result,
    )
