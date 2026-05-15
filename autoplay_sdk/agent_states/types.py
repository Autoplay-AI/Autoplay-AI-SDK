"""Enums and dataclasses for session-level agent states (copilot FSM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentState(StrEnum):
    """Operational states the agent session can be in (not LangGraph graph nodes)."""

    THINKING = "thinking"
    REACTIVE_ASSISTANCE = "reactive_assistance"
    PROACTIVE_ASSISTANCE = "proactive_assistance"
    GUIDANCE_EXECUTION = "guidance_execution"
    CONSERVATIVE_ASSISTANCE = "conservative_assistance"


class InvalidTransitionError(ValueError):
    """Raised when a requested transition is not allowed from the current state."""


class InvalidSnapshotError(ValueError):
    """Raised when ``from_snapshot`` receives malformed or unsupported data."""


@dataclass
class TaskProgress:
    """Tracks one golden-path walkthrough attempt."""

    flow_id: str
    flow_name: str
    started_at: float
    total_steps: int
    steps_completed: int = 0
    current_step_index: int = 0
    best_nw_score: float = 0.0
    attempts: int = 1
    guidance_engaged: bool = False
    abandoned: bool = False
    completed: bool = False
    deviation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "flow_name": self.flow_name,
            "started_at": self.started_at,
            "total_steps": self.total_steps,
            "steps_completed": self.steps_completed,
            "current_step_index": self.current_step_index,
            "best_nw_score": self.best_nw_score,
            "attempts": self.attempts,
            "guidance_engaged": self.guidance_engaged,
            "abandoned": self.abandoned,
            "completed": self.completed,
            "deviation_count": self.deviation_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskProgress:
        return cls(
            flow_id=str(data["flow_id"]),
            flow_name=str(data["flow_name"]),
            started_at=float(data["started_at"]),
            total_steps=int(data["total_steps"]),
            steps_completed=int(data.get("steps_completed", 0)),
            current_step_index=int(data.get("current_step_index", 0)),
            best_nw_score=float(data.get("best_nw_score", 0.0)),
            attempts=int(data.get("attempts", 1)),
            guidance_engaged=bool(data.get("guidance_engaged", False)),
            abandoned=bool(data.get("abandoned", False)),
            completed=bool(data.get("completed", False)),
            deviation_count=int(data.get("deviation_count", 0)),
        )


@dataclass
class SessionMetrics:
    """Accumulates per-session counters."""

    tasks_attempted: set[str] = field(default_factory=set)
    tasks_completed: set[str] = field(default_factory=set)
    tasks_abandoned: set[str] = field(default_factory=set)
    proactive_shown_count: int = 0
    guidance_accepted_count: int = 0
    dismissal_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks_attempted": sorted(self.tasks_attempted),
            "tasks_completed": sorted(self.tasks_completed),
            "tasks_abandoned": sorted(self.tasks_abandoned),
            "proactive_shown_count": self.proactive_shown_count,
            "guidance_accepted_count": self.guidance_accepted_count,
            "dismissal_count": self.dismissal_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetrics:
        return cls(
            tasks_attempted=set(data.get("tasks_attempted") or []),
            tasks_completed=set(data.get("tasks_completed") or []),
            tasks_abandoned=set(data.get("tasks_abandoned") or []),
            proactive_shown_count=int(data.get("proactive_shown_count", 0)),
            guidance_accepted_count=int(data.get("guidance_accepted_count", 0)),
            dismissal_count=int(data.get("dismissal_count", 0)),
        )


@dataclass(frozen=True)
class ProactiveIdleExpiryResult:
    """Outcome of :meth:`~autoplay_sdk.agent_states.AgentStateMachine.expire_proactive_to_thinking_if_idle`."""

    transitioned: bool
    reset_chat_thread_binding: bool = False

    def __bool__(self) -> bool:
        return self.transitioned
