"""Unit tests for autoplay_sdk.agent_states.AgentStateMachine."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from autoplay_sdk.agent_states import (
    AgentState,
    AgentStateMachine,
    InvalidSnapshotError,
    InvalidTransitionError,
)


def test_initial_state_is_thinking() -> None:
    sm = AgentStateMachine()
    assert sm.state == AgentState.THINKING


def test_thinking_to_proactive() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    assert sm.state == AgentState.PROACTIVE_ASSISTANCE


def test_thinking_to_reactive() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.REACTIVE_ASSISTANCE)
    assert sm.state == AgentState.REACTIVE_ASSISTANCE


def test_enter_reactive_from_user_message_noop_when_already_reactive() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.REACTIVE_ASSISTANCE)
    sm.enter_reactive_from_user_message()
    assert sm.state == AgentState.REACTIVE_ASSISTANCE


def test_enter_reactive_from_user_message_from_proactive() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    sm.enter_reactive_from_user_message(
        reason="inbound_user_message_overrides_proactive"
    )
    assert sm.state == AgentState.REACTIVE_ASSISTANCE


def test_enter_reactive_from_user_message_logs_and_reraises_invalid_transition() -> (
    None
):
    sm = AgentStateMachine()
    sm.state = AgentState.THINKING
    with (
        patch.object(
            sm,
            "transition_to",
            side_effect=InvalidTransitionError("forced"),
        ),
        patch("autoplay_sdk.agent_states.state_machine.logger.warning") as warn,
    ):
        with pytest.raises(InvalidTransitionError, match="forced"):
            sm.enter_reactive_from_user_message(reason="inbound_user_message")
    warn.assert_called_once()


def test_invalid_transition_raises() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason="test")
    with pytest.raises(InvalidTransitionError, match="Invalid transition"):
        sm.transition_to(AgentState.GUIDANCE_EXECUTION)


def test_same_state_transition_is_noop() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.THINKING)
    assert sm.state == AgentState.THINKING


def test_proactive_accepted_to_guidance() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("flow_1", "Create Contact", 5)
    sm.transition_to(
        AgentState.GUIDANCE_EXECUTION,
        task=task,
        instructions=[{"action": "click"}],
    )
    assert sm.state == AgentState.GUIDANCE_EXECUTION
    assert sm.active_guidance_flow_id == "flow_1"
    assert task.guidance_engaged is True
    assert sm.session_metrics.guidance_accepted_count == 1


def test_proactive_dismissed_to_conservative() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    sm.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason="dismissed")
    assert sm.state == AgentState.CONSERVATIVE_ASSISTANCE
    assert sm.current_threshold > sm.base_threshold
    assert sm.session_metrics.dismissal_count == 1


def test_guidance_disengagement_to_conservative() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("f1", "Flow", 3)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task)
    sm.transition_on_disengagement(reason="timeout")
    assert sm.state == AgentState.CONSERVATIVE_ASSISTANCE


def test_conservative_escalation() -> None:
    sm = AgentStateMachine(base_threshold=0.5, conservative_threshold_boost=0.15)

    for _ in range(3):
        if sm.state == AgentState.CONSERVATIVE_ASSISTANCE:
            sm._conservative_cooldown_until = 0.0
            sm.state = AgentState.THINKING
        sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
        sm.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason="dismissed")

    assert sm.dismissed_count_session == 3
    assert sm.current_threshold == 0.9
    assert sm._conservative_cooldown_until == float("inf")


def test_conservative_cooldown_expires() -> None:
    sm = AgentStateMachine(conservative_cooldown_s=0.0)
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    sm.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason="dismissed")
    assert sm.state == AgentState.CONSERVATIVE_ASSISTANCE

    sm._conservative_cooldown_until = time.time() - 1

    assert sm.can_show_proactive() is True
    assert sm.state == AgentState.THINKING


def test_can_show_proactive_with_reason_wrong_state() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.REACTIVE_ASSISTANCE)
    ok, reason = sm.can_show_proactive_with_reason()
    assert ok is False
    assert reason == "wrong_state"


def test_expire_proactive_to_thinking_if_idle_transitions() -> None:
    with patch("autoplay_sdk.agent_states.state_machine.time") as mock_time:
        mock_time.time.return_value = 1000.0
        sm = AgentStateMachine()
        sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
        entered = sm.state_entered_at
        assert entered == 1000.0
        assert not sm.expire_proactive_to_thinking_if_idle(1009.0, 10.0)
        assert sm.state == AgentState.PROACTIVE_ASSISTANCE
        mock_time.time.return_value = 1010.0
        r = sm.expire_proactive_to_thinking_if_idle(1010.0, 10.0)
        assert r.transitioned and r.reset_chat_thread_binding
        assert r
        assert sm.state == AgentState.THINKING
        assert sm.state_entered_at == 1010.0


def test_expire_proactive_to_thinking_if_idle_wrong_state_noop() -> None:
    sm = AgentStateMachine()
    assert not sm.expire_proactive_to_thinking_if_idle(time.time(), 10.0)


@pytest.mark.asyncio
async def test_run_proactive_idle_expiry_order_and_hooks() -> None:
    from autoplay_sdk.agent_states.proactive_idle_expiry import (
        ProactiveIdleExpiryPipelineStatus,
        run_proactive_idle_expiry,
    )

    order: list[str] = []

    class Hooks:
        async def delete_remote_chat_thread(self) -> bool:
            order.append("delete")
            return True

        async def clear_local_chat_thread_state(self) -> None:
            order.append("clear")

    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    sm.state_entered_at = 0.0

    out = await run_proactive_idle_expiry(
        sm,
        now=100.0,
        interaction_timeout_s=10.0,
        hooks=Hooks(),
    )
    assert out.status == ProactiveIdleExpiryPipelineStatus.COMPLETED
    assert order == ["delete", "clear"]
    assert sm.state == AgentState.THINKING


@pytest.mark.asyncio
async def test_run_proactive_idle_expiry_skips_when_delete_fails() -> None:
    from autoplay_sdk.agent_states.proactive_idle_expiry import (
        ProactiveIdleExpiryPipelineStatus,
        run_proactive_idle_expiry,
    )

    class Hooks:
        async def delete_remote_chat_thread(self) -> bool:
            return False

        async def clear_local_chat_thread_state(self) -> None:
            raise AssertionError("clear must not run")

    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    sm.state_entered_at = 0.0

    out = await run_proactive_idle_expiry(
        sm,
        now=100.0,
        interaction_timeout_s=10.0,
        hooks=Hooks(),
    )
    assert out.status == ProactiveIdleExpiryPipelineStatus.REMOTE_DELETE_FAILED
    assert sm.state == AgentState.PROACTIVE_ASSISTANCE


def test_snapshot_round_trip() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("a", "A", 2)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task, instructions=[{"x": 1}])
    snap = sm.to_snapshot()
    sm2 = AgentStateMachine.from_snapshot(snap)
    assert sm2.state == AgentState.GUIDANCE_EXECUTION
    assert sm2.active_guidance_flow_id == "a"
    assert sm2.active_guidance_instructions == [{"x": 1}]
    assert sm2.session_metrics.guidance_accepted_count == 1


def test_from_snapshot_bad_version() -> None:
    with pytest.raises(InvalidSnapshotError):
        AgentStateMachine.from_snapshot({"_v": 999, "state": "thinking"})


def test_guidance_step_completion() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("flow_1", "Create Contact", 5)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task)

    sm.record_step_completion("flow_1", 0)
    sm.record_step_completion("flow_1", 1)
    assert task.steps_completed == 2
    assert task.current_step_index == 1


def test_guidance_task_completion() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("flow_1", "Create Contact", 3)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task)

    sm.complete_task("flow_1")
    assert task.completed is True
    assert task.steps_completed == 3
    assert sm.state == AgentState.THINKING
    assert sm.active_guidance_flow_id is None
    assert "flow_1" in sm.session_metrics.tasks_completed


def test_session_snapshot_format() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("flow_1", "Create Contact", 5)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task, instructions=[])

    sm.record_step_completion("flow_1", 0)
    sm.record_step_completion("flow_1", 1)

    snap = sm.get_session_snapshot()
    assert len(snap["tasks"]) == 1
    t = snap["tasks"][0]
    assert t["flow_id"] == "flow_1"
    assert snap["guidance_accepted"] == 1
    assert snap["last_active_flow"] == "flow_1"


def test_can_show_proactive_route_cooldown() -> None:
    sm = AgentStateMachine()
    sm.set_route_cooldown("/contacts", 300)
    assert sm.can_show_proactive(route="/contacts") is False
    assert sm.can_show_proactive(route="/dashboard") is True


def test_cannot_show_proactive_during_guidance() -> None:
    sm = AgentStateMachine()
    sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
    task = sm.start_task("f1", "Test", 3)
    sm.transition_to(AgentState.GUIDANCE_EXECUTION, task=task)
    assert sm.can_show_proactive() is False
