"""Hand-rolled session FSM: reactive vs proactive vs guidance execution vs conservative."""

from __future__ import annotations

import logging
import time
from typing import Any

from autoplay_sdk.agent_states.types import (
    AgentState,
    InvalidSnapshotError,
    InvalidTransitionError,
    ProactiveIdleExpiryResult,
    SessionMetrics,
    TaskProgress,
)

logger = logging.getLogger(__name__)

_SNAPSHOT_VERSION = 1

# Stable ``extra["event_type"]`` values (see ``docs/sdk/logging.mdx``).
_EV_TRANSITION = "agent_state_transition"
_EV_TRANSITION_REJECTED = "agent_state_transition_rejected"
_EV_SNAPSHOT_UNSUPPORTED_VERSION = "agent_states_snapshot_unsupported_version"
_EV_SNAPSHOT_INVALID = "agent_states_snapshot_invalid"
_EV_SNAPSHOT_TASK_SKIP = "agent_states_snapshot_task_skipped"
_EV_TRANSITION_COMPLETE_TASK = "agent_state_transition_complete_task"

# Research-archive baseline + guidance_execution → conservative (disengagement / abandon).
_VALID_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.THINKING: frozenset(
        {
            AgentState.PROACTIVE_ASSISTANCE,
            AgentState.REACTIVE_ASSISTANCE,
            AgentState.CONSERVATIVE_ASSISTANCE,
        }
    ),
    AgentState.PROACTIVE_ASSISTANCE: frozenset(
        {
            AgentState.GUIDANCE_EXECUTION,
            AgentState.CONSERVATIVE_ASSISTANCE,
            AgentState.THINKING,
            AgentState.REACTIVE_ASSISTANCE,
        }
    ),
    AgentState.GUIDANCE_EXECUTION: frozenset(
        {
            AgentState.THINKING,
            AgentState.REACTIVE_ASSISTANCE,
            AgentState.CONSERVATIVE_ASSISTANCE,
        }
    ),
    AgentState.REACTIVE_ASSISTANCE: frozenset(
        {
            AgentState.THINKING,
            AgentState.GUIDANCE_EXECUTION,
        }
    ),
    AgentState.CONSERVATIVE_ASSISTANCE: frozenset(
        {
            AgentState.THINKING,
            AgentState.REACTIVE_ASSISTANCE,
        }
    ),
}


class AgentStateMachine:
    """Five-state FSM for copilot session gating (proactive / reactive / walkthrough)."""

    def __init__(
        self,
        *,
        base_threshold: float = 0.5,
        max_tasks: int = 3,
        conservative_cooldown_s: float = 600.0,
        conservative_threshold_boost: float = 0.15,
        guidance_deviation_threshold: float = 0.3,
    ) -> None:
        self.state = AgentState.THINKING
        self.state_entered_at: float = time.time()

        self.base_threshold = base_threshold
        self.current_threshold = base_threshold
        self.max_tasks = max_tasks
        self.active_tasks: dict[str, TaskProgress] = {}
        self.dismissed_count_session: int = 0

        self.active_guidance_flow_id: str | None = None
        self.active_guidance_instructions: list[dict[str, Any]] = []

        self._conservative_cooldown_s = conservative_cooldown_s
        self._threshold_boost = conservative_threshold_boost
        self._conservative_cooldown_until: float = 0.0

        self._deviation_threshold = guidance_deviation_threshold

        self.route_cooldowns: dict[str, float] = {}
        self.flow_cooldowns: dict[str, float] = {}

        self.session_metrics = SessionMetrics()

    def transition_to(
        self,
        target: AgentState,
        *,
        reason: str = "",
        task: TaskProgress | None = None,
        instructions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Move to ``target``. Raises ``InvalidTransitionError`` if illegal."""
        if target == self.state:
            return

        allowed = _VALID_TRANSITIONS.get(self.state, frozenset())
        if target not in allowed:
            logger.debug(
                "agent_states: rejected transition %s -> %s reason=%s",
                self.state.value,
                target.value,
                (reason or "")[:200],
                extra={
                    "event_type": _EV_TRANSITION_REJECTED,
                    "from_state": self.state.value,
                    "to_state": target.value,
                    "reason_preview": (reason or "")[:200],
                },
            )
            raise InvalidTransitionError(
                f"Invalid transition: {self.state.value} -> {target.value}"
            )

        old = self.state
        self.state = target
        self.state_entered_at = time.time()

        if target == AgentState.PROACTIVE_ASSISTANCE:
            self.session_metrics.proactive_shown_count += 1

        elif target == AgentState.GUIDANCE_EXECUTION:
            if task:
                self.active_guidance_flow_id = task.flow_id
                task.guidance_engaged = True
            if instructions is not None:
                self.active_guidance_instructions = instructions
            self.session_metrics.guidance_accepted_count += 1

        elif target == AgentState.CONSERVATIVE_ASSISTANCE:
            self._on_enter_conservative(reason)

        elif target == AgentState.THINKING:
            if old == AgentState.GUIDANCE_EXECUTION:
                self.active_guidance_flow_id = None
                self.active_guidance_instructions = []

        logger.debug(
            "agent_states: transition %s -> %s reason=%s",
            old.value,
            target.value,
            (reason or "")[:200],
            extra={
                "event_type": _EV_TRANSITION,
                "from_state": old.value,
                "to_state": target.value,
                "reason_preview": (reason or "")[:200],
            },
        )

    def enter_reactive_from_user_message(
        self, *, reason: str = "inbound_user_message"
    ) -> None:
        """Move to ``reactive_assistance`` when the user sends a normal chat message.

        Hosts (e.g. Intercom inbound) call this so typed user text overrides proactive
        UI without duplicating the transition matrix. No-op if already reactive.
        Raises :class:`InvalidTransitionError` when the edge is illegal.
        """
        if self.state == AgentState.REACTIVE_ASSISTANCE:
            return
        try:
            self.transition_to(AgentState.REACTIVE_ASSISTANCE, reason=reason)
        except InvalidTransitionError:
            logger.warning(
                "agent_states: enter_reactive_from_user_message rejected current=%s reason=%s",
                self.state.value,
                (reason or "")[:200],
                extra={
                    "event_type": _EV_TRANSITION_REJECTED,
                    "from_state": self.state.value,
                    "to_state": AgentState.REACTIVE_ASSISTANCE.value,
                    "operation": "enter_reactive_from_user_message",
                    "reason_preview": (reason or "")[:200],
                },
            )
            raise

    def transition_on_disengagement(self, *, reason: str = "disengaged") -> None:
        """Leave an active guidance flow without completing (user ghosted / timed out).

        Moves ``guidance_execution`` → ``conservative_assistance`` when allowed.
        """
        if self.state != AgentState.GUIDANCE_EXECUTION:
            logger.debug(
                "agent_states: transition_on_disengagement rejected current=%s",
                self.state.value,
                extra={
                    "event_type": _EV_TRANSITION_REJECTED,
                    "from_state": self.state.value,
                    "operation": "transition_on_disengagement",
                },
            )
            raise InvalidTransitionError(
                f"transition_on_disengagement only from guidance_execution; "
                f"current={self.state.value}"
            )
        self.transition_to(AgentState.CONSERVATIVE_ASSISTANCE, reason=reason)

    def _on_enter_conservative(self, reason: str) -> None:
        self.dismissed_count_session += 1
        self.session_metrics.dismissal_count += 1
        n = self.dismissed_count_session
        cooldown = self._conservative_cooldown_s + (n - 1) * 300
        self._conservative_cooldown_until = time.time() + cooldown
        self.current_threshold = min(
            0.9, self.base_threshold + self._threshold_boost * n
        )
        if n >= 3:
            self._conservative_cooldown_until = float("inf")

    def can_show_proactive_with_reason(
        self, route: str = "", flow_name: str = ""
    ) -> tuple[bool, str]:
        """Whether a proactive offer may be shown; second value is a stable reason code."""
        now = time.time()

        if self.state == AgentState.CONSERVATIVE_ASSISTANCE:
            if now >= self._conservative_cooldown_until:
                self.state = AgentState.THINKING
                self.state_entered_at = now
            else:
                return False, "conservative_cooldown"

        if self.state != AgentState.THINKING:
            return False, "wrong_state"

        if route and now < self.route_cooldowns.get(route, 0.0):
            return False, "route_cooldown"

        if flow_name and now < self.flow_cooldowns.get(flow_name, 0.0):
            return False, "flow_cooldown"

        return True, "ok"

    def can_show_proactive(self, route: str = "", flow_name: str = "") -> bool:
        """Same as :meth:`can_show_proactive_with_reason` but returns only the boolean."""
        return self.can_show_proactive_with_reason(route, flow_name)[0]

    def expire_proactive_to_thinking_if_idle(
        self, now: float, interaction_timeout_s: float
    ) -> ProactiveIdleExpiryResult:
        """If in ``proactive_assistance`` and idle for ``interaction_timeout_s``, go to ``thinking``.

        Pass ``interaction_timeout_s`` from :attr:`ProactiveTriggerResult.interaction_timeout_s`
        when ticking the session. **Interaction** (tap, dismiss, etc.) is detected by your app;
        this only compares ``now`` to :attr:`state_entered_at`.

        Returns :class:`~autoplay_sdk.agent_states.types.ProactiveIdleExpiryResult`; truthy when
        a transition was performed. When ``transitioned`` is true, ``reset_chat_thread_binding``
        is true (pair with :func:`~autoplay_sdk.agent_states.proactive_idle_expiry.run_proactive_idle_expiry`
        for chat integrations that delete the remote thread before transitioning).
        """
        if self.state != AgentState.PROACTIVE_ASSISTANCE:
            return ProactiveIdleExpiryResult(
                transitioned=False, reset_chat_thread_binding=False
            )
        if now - self.state_entered_at < interaction_timeout_s:
            return ProactiveIdleExpiryResult(
                transitioned=False, reset_chat_thread_binding=False
            )
        self.transition_to(
            AgentState.THINKING,
            reason="proactive_interaction_timeout",
        )
        return ProactiveIdleExpiryResult(
            transitioned=True, reset_chat_thread_binding=True
        )

    def get_effective_threshold(self) -> float:
        return self.current_threshold

    def set_route_cooldown(self, route: str, seconds: float) -> None:
        self.route_cooldowns[route] = time.time() + seconds

    def set_flow_cooldown(self, flow_name: str, seconds: float) -> None:
        if flow_name:
            self.flow_cooldowns[flow_name] = time.time() + seconds

    def start_task(
        self, flow_id: str, flow_name: str, total_steps: int
    ) -> TaskProgress:
        existing = self.active_tasks.get(flow_id)
        if existing:
            existing.attempts += 1
            existing.abandoned = False
            existing.completed = False
            existing.steps_completed = 0
            existing.current_step_index = 0
            existing.deviation_count = 0
            existing.started_at = time.time()
            return existing

        task = TaskProgress(
            flow_id=flow_id,
            flow_name=flow_name,
            started_at=time.time(),
            total_steps=total_steps,
        )
        self.active_tasks[flow_id] = task
        self.session_metrics.tasks_attempted.add(flow_id)
        return task

    def complete_task(self, flow_id: str) -> None:
        task = self.active_tasks.get(flow_id)
        if task:
            task.completed = True
            task.steps_completed = task.total_steps
            self.session_metrics.tasks_completed.add(flow_id)

        if self.state == AgentState.GUIDANCE_EXECUTION:
            self.active_guidance_flow_id = None
            self.active_guidance_instructions = []
            old = self.state
            self.state = AgentState.THINKING
            self.state_entered_at = time.time()
            logger.debug(
                "agent_states: transition %s -> %s flow_id=%s",
                old.value,
                self.state.value,
                flow_id[:80],
                extra={
                    "event_type": _EV_TRANSITION_COMPLETE_TASK,
                    "from_state": old.value,
                    "to_state": self.state.value,
                    "flow_id": flow_id[:80],
                },
            )

    def abandon_task(self, flow_id: str) -> None:
        task = self.active_tasks.get(flow_id)
        if task:
            task.abandoned = True
            self.session_metrics.tasks_abandoned.add(flow_id)

    def record_step_completion(self, flow_id: str, step_index: int) -> None:
        task = self.active_tasks.get(flow_id)
        if task:
            task.current_step_index = step_index
            task.steps_completed = max(task.steps_completed, step_index + 1)

    def record_deviation(self, flow_id: str, nw_score: float) -> bool:
        task = self.active_tasks.get(flow_id)
        if not task:
            return False
        task.deviation_count += 1
        return nw_score < self._deviation_threshold

    @property
    def proactive_state_dict(self) -> dict[str, object]:
        popup_active = self.state in (
            AgentState.PROACTIVE_ASSISTANCE,
            AgentState.GUIDANCE_EXECUTION,
        )
        return {
            "global_cooldown_until": self._conservative_cooldown_until,
            "route_cooldowns": self.route_cooldowns,
            "flow_cooldowns": self.flow_cooldowns,
            "popup_active": popup_active,
            "popup_active_since": self.state_entered_at if popup_active else 0.0,
        }

    def get_session_snapshot(self) -> dict[str, Any]:
        return {
            "tasks": [
                {
                    "flow_id": t.flow_id,
                    "flow_name": t.flow_name,
                    "completed": t.completed,
                    "abandoned": t.abandoned,
                    "steps_completed": t.steps_completed,
                    "total_steps": t.total_steps,
                    "best_nw_score": round(t.best_nw_score, 3),
                    "attempts": t.attempts,
                    "guidance_engaged": t.guidance_engaged,
                    "score": round(t.best_nw_score, 3),
                    "matched_steps": t.steps_completed,
                    "name": t.flow_name,
                }
                for t in self.active_tasks.values()
            ],
            "proactive_shown": self.session_metrics.proactive_shown_count,
            "guidance_accepted": self.session_metrics.guidance_accepted_count,
            "dismissals": self.session_metrics.dismissal_count,
            "last_state": self.state.value,
            "last_active_flow": self.active_guidance_flow_id,
        }

    def to_snapshot(self) -> dict[str, Any]:
        """JSON-serializable dict for Redis / multi-worker restore."""
        return {
            "_v": _SNAPSHOT_VERSION,
            "state": self.state.value,
            "state_entered_at": self.state_entered_at,
            "base_threshold": self.base_threshold,
            "current_threshold": self.current_threshold,
            "max_tasks": self.max_tasks,
            "dismissed_count_session": self.dismissed_count_session,
            "active_guidance_flow_id": self.active_guidance_flow_id,
            "active_guidance_instructions": list(self.active_guidance_instructions),
            "active_tasks": {k: v.to_dict() for k, v in self.active_tasks.items()},
            "session_metrics": self.session_metrics.to_dict(),
            "conservative_cooldown_s": self._conservative_cooldown_s,
            "threshold_boost": self._threshold_boost,
            "conservative_cooldown_until": self._conservative_cooldown_until,
            "deviation_threshold": self._deviation_threshold,
            "route_cooldowns": dict(self.route_cooldowns),
            "flow_cooldowns": dict(self.flow_cooldowns),
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> AgentStateMachine:
        if not isinstance(data, dict):
            logger.warning(
                "agent_states: snapshot must be a dict, got %s",
                type(data).__name__,
                extra={
                    "event_type": _EV_SNAPSHOT_INVALID,
                    "value_type": type(data).__name__,
                },
            )
            raise InvalidSnapshotError("Snapshot must be a dict.")
        ver = data.get("_v")
        if ver != _SNAPSHOT_VERSION:
            logger.warning(
                "agent_states: unsupported snapshot _v=%r expected=%s",
                ver,
                _SNAPSHOT_VERSION,
                extra={
                    "event_type": _EV_SNAPSHOT_UNSUPPORTED_VERSION,
                    "snapshot_v": ver,
                    "expected_v": _SNAPSHOT_VERSION,
                },
            )
            raise InvalidSnapshotError(
                f"Unsupported snapshot _v={ver!r}; expected {_SNAPSHOT_VERSION}."
            )
        try:
            st = AgentState(str(data["state"]))
        except (KeyError, ValueError) as exc:
            logger.warning(
                "agent_states: invalid state field in snapshot: %s",
                exc,
                exc_info=True,
                extra={"event_type": _EV_SNAPSHOT_INVALID},
            )
            raise InvalidSnapshotError(f"Invalid state: {exc}") from exc

        sm = cls(
            base_threshold=float(data.get("base_threshold", 0.5)),
            max_tasks=int(data.get("max_tasks", 3)),
            conservative_cooldown_s=float(data.get("conservative_cooldown_s", 600.0)),
            conservative_threshold_boost=float(data.get("threshold_boost", 0.15)),
            guidance_deviation_threshold=float(data.get("deviation_threshold", 0.3)),
        )
        sm.state = st
        sm.state_entered_at = float(data.get("state_entered_at", time.time()))
        sm.current_threshold = float(data.get("current_threshold", sm.base_threshold))
        sm.dismissed_count_session = int(data.get("dismissed_count_session", 0))
        sm.active_guidance_flow_id = data.get("active_guidance_flow_id")
        raw_instr = data.get("active_guidance_instructions")
        if isinstance(raw_instr, list):
            sm.active_guidance_instructions = [
                dict(x) for x in raw_instr if isinstance(x, dict)
            ]
        elif raw_instr is None:
            sm.active_guidance_instructions = []
        else:
            sm.active_guidance_instructions = []

        sm._conservative_cooldown_until = float(
            data.get("conservative_cooldown_until", 0.0)
        )
        sm.route_cooldowns = dict(data.get("route_cooldowns") or {})
        sm.flow_cooldowns = dict(data.get("flow_cooldowns") or {})

        sm.active_tasks.clear()
        for tid, tdata in (data.get("active_tasks") or {}).items():
            if isinstance(tdata, dict):
                try:
                    sm.active_tasks[str(tid)] = TaskProgress.from_dict(tdata)
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "agent_states: skip bad task %s in snapshot: %s",
                        tid,
                        exc,
                        exc_info=True,
                        extra={
                            "event_type": _EV_SNAPSHOT_TASK_SKIP,
                            "task_id_preview": str(tid)[:80],
                        },
                    )

        sm.session_metrics = SessionMetrics.from_dict(data.get("session_metrics") or {})
        return sm


def proactive_idle_eligible(
    sm: AgentStateMachine, now: float, interaction_timeout_s: float
) -> bool:
    """True when :meth:`AgentStateMachine.expire_proactive_to_thinking_if_idle` would transition (no mutation)."""
    if sm.state != AgentState.PROACTIVE_ASSISTANCE:
        return False
    if now - sm.state_entered_at < interaction_timeout_s:
        return False
    return True
