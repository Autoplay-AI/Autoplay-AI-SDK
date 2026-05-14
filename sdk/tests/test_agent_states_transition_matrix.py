"""Exercises every directed edge in ``_VALID_TRANSITIONS`` plus illegal samples.

White-box import of ``_VALID_TRANSITIONS`` ensures the matrix stays aligned with
the FSM graph in ``state_machine.py``.
"""

from __future__ import annotations

import pytest

from autoplay_sdk.agent_states import (
    AgentState,
    AgentStateMachine,
    InvalidTransitionError,
)
from autoplay_sdk.agent_states.state_machine import _VALID_TRANSITIONS


def _machine_in_state(target: AgentState) -> AgentStateMachine:
    """Reach ``target`` from a fresh machine using only legal transitions."""
    sm = AgentStateMachine()
    if target == AgentState.THINKING:
        return sm
    if target == AgentState.REACTIVE_ASSISTANCE:
        sm.transition_to(AgentState.REACTIVE_ASSISTANCE)
        return sm
    if target == AgentState.PROACTIVE_ASSISTANCE:
        sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
        return sm
    if target == AgentState.CONSERVATIVE_ASSISTANCE:
        sm.transition_to(AgentState.CONSERVATIVE_ASSISTANCE)
        return sm
    if target == AgentState.GUIDANCE_EXECUTION:
        sm.transition_to(AgentState.PROACTIVE_ASSISTANCE)
        task = sm.start_task("matrix_flow", "Matrix", 5)
        sm.transition_to(
            AgentState.GUIDANCE_EXECUTION,
            task=task,
            instructions=[{"action": "click"}],
        )
        return sm
    raise AssertionError(f"unhandled target {target!r}")


def _all_directed_edges():
    for from_state, targets in _VALID_TRANSITIONS.items():
        for to_state in targets:
            if from_state == to_state:
                continue
            yield from_state, to_state


_LEGAL_EDGES = list(_all_directed_edges())
_LEGAL_IDS = [f"{a.value}->{b.value}" for a, b in _LEGAL_EDGES]


@pytest.mark.parametrize("from_state,to_state", _LEGAL_EDGES, ids=_LEGAL_IDS)
def test_legal_transition_matrix(from_state: AgentState, to_state: AgentState) -> None:
    sm = _machine_in_state(from_state)
    assert sm.state == from_state

    if (from_state, to_state) == (
        AgentState.PROACTIVE_ASSISTANCE,
        AgentState.GUIDANCE_EXECUTION,
    ):
        task = sm.start_task("edge_flow", "Edge", 3)
        sm.transition_to(
            AgentState.GUIDANCE_EXECUTION,
            task=task,
            instructions=[{"step": 1}],
        )
    elif (from_state, to_state) == (
        AgentState.REACTIVE_ASSISTANCE,
        AgentState.GUIDANCE_EXECUTION,
    ):
        task = sm.start_task("edge_flow", "Edge", 3)
        sm.transition_to(
            AgentState.GUIDANCE_EXECUTION,
            task=task,
            instructions=[{"step": 1}],
        )
    else:
        sm.transition_to(to_state)

    assert sm.state == to_state


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (AgentState.THINKING, AgentState.GUIDANCE_EXECUTION),
        (AgentState.REACTIVE_ASSISTANCE, AgentState.PROACTIVE_ASSISTANCE),
        (AgentState.REACTIVE_ASSISTANCE, AgentState.CONSERVATIVE_ASSISTANCE),
        (AgentState.GUIDANCE_EXECUTION, AgentState.PROACTIVE_ASSISTANCE),
        (AgentState.CONSERVATIVE_ASSISTANCE, AgentState.PROACTIVE_ASSISTANCE),
        (AgentState.CONSERVATIVE_ASSISTANCE, AgentState.GUIDANCE_EXECUTION),
    ],
    ids=[
        "thinking-X-guidance_execution",
        "reactive-X-proactive",
        "reactive-X-conservative",
        "guidance-X-proactive",
        "conservative-X-proactive",
        "conservative-X-guidance_execution",
    ],
)
def test_illegal_transition_raises(
    from_state: AgentState, to_state: AgentState
) -> None:
    sm = _machine_in_state(from_state)
    with pytest.raises(InvalidTransitionError, match="Invalid transition"):
        if to_state == AgentState.GUIDANCE_EXECUTION:
            task = sm.start_task("bad", "Bad", 2)
            sm.transition_to(to_state, task=task, instructions=[])
        else:
            sm.transition_to(to_state)


def test_transition_on_disengagement_moves_to_conservative() -> None:
    sm = _machine_in_state(AgentState.GUIDANCE_EXECUTION)
    sm.transition_on_disengagement(reason="timeout")
    assert sm.state == AgentState.CONSERVATIVE_ASSISTANCE


def test_transition_on_disengagement_only_from_guidance() -> None:
    sm = AgentStateMachine()
    with pytest.raises(InvalidTransitionError, match="transition_on_disengagement"):
        sm.transition_on_disengagement()


def test_transition_on_disengagement_equivalent_to_transition_to_conservative() -> None:
    sm1 = _machine_in_state(AgentState.GUIDANCE_EXECUTION)
    sm1.transition_on_disengagement(reason="a")

    sm2 = _machine_in_state(AgentState.GUIDANCE_EXECUTION)
    sm2.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason="a")

    assert sm1.state == sm2.state == AgentState.CONSERVATIVE_ASSISTANCE
    assert sm1.dismissed_count_session == sm2.dismissed_count_session
