"""Per-user adoption state model.

This is a per-``user_id`` record that is orthogonal to the per-session
``AgentStateV2`` FSM. It captures the user's longer-term product maturity and
onboarding lifecycle:

- ``metadata``       : a fully dynamic, schema-less bag (role, email, team, ...).
- ``journey_state``  : coarse lifecycle (onboarding / onboarded).
- ``mastery``        : rating 0-10 + spectrum level + reason.
- ``onboarding``     : welcome lifecycle + per-flow ``WorkflowProgress`` beliefs
                       inferred asynchronously from the live click stream.

All dataclasses provide ``to_dict`` / ``from_dict`` so the whole record
round-trips through Redis. ``from_dict`` is defensive (coerces unknown enum
values to safe defaults) mirroring ``SessionState.from_dict``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from autoplay_sdk.user_adoption_state.types import (
    JourneyState,
    MasteryLevel,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)

_SNAPSHOT_VERSION = 1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Mastery
# ---------------------------------------------------------------------------


@dataclass
class Mastery:
    """The "/10 + reason" rating.

    rating      : 0-10 score (clamped on construction via ``make``).
    level       : spectrum band kept consistent with ``rating``.
    description : short natural-language reason for the rating.
    """

    rating: int = 0
    level: MasteryLevel = MasteryLevel.NOVICE
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rating": self.rating,
            "level": self.level.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Mastery:
        d = d or {}
        try:
            level = MasteryLevel(d.get("level", MasteryLevel.NOVICE.value))
        except ValueError:
            level = MasteryLevel.NOVICE
        rating_raw = d.get("rating", 0)
        try:
            rating = int(_clamp(float(rating_raw), 0, 10))
        except (TypeError, ValueError):
            rating = 0
        return cls(
            rating=rating, level=level, description=str(d.get("description", ""))
        )


# ---------------------------------------------------------------------------
# WorkflowProgress
# ---------------------------------------------------------------------------


@dataclass
class WorkflowProgress:
    """The agent's evolving belief about one target onboarding flow.

    The agent updates this over time as more live activity streams in. Keeping
    ``confidence`` + ``evidence`` makes the decision explainable and stable.
    """

    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    confidence: float = 0.0
    evidence: str = ""
    first_detected_at: float | None = None
    completed_at: float | None = None
    last_evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "first_detected_at": self.first_detected_at,
            "completed_at": self.completed_at,
            "last_evaluated_at": self.last_evaluated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkflowProgress:
        try:
            status = WorkflowStatus(d.get("status", WorkflowStatus.NOT_STARTED.value))
        except ValueError:
            status = WorkflowStatus.NOT_STARTED
        try:
            confidence = _clamp(float(d.get("confidence", 0.0)), 0.0, 1.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            workflow_id=str(d.get("workflow_id", "")),
            status=status,
            confidence=confidence,
            evidence=str(d.get("evidence", "")),
            first_detected_at=d.get("first_detected_at"),
            completed_at=d.get("completed_at"),
            last_evaluated_at=d.get("last_evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# StepInAssessment
# ---------------------------------------------------------------------------


@dataclass
class StepInAssessment:
    """The agent's latest "should I step in?" decision.

    Persisted whether or not we actually sent anything, so timing is
    explainable, debuggable, and paced.
    """

    decided_at: float = field(default_factory=time.time)
    should_step_in: bool = False
    timing_assessment: str = ""
    reason: str = ""
    suggested_workflow_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decided_at": self.decided_at,
            "should_step_in": self.should_step_in,
            "timing_assessment": self.timing_assessment,
            "reason": self.reason,
            "suggested_workflow_ids": list(self.suggested_workflow_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> StepInAssessment | None:
        if not d:
            return None
        return cls(
            decided_at=d.get("decided_at", time.time()),
            should_step_in=bool(d.get("should_step_in", False)),
            timing_assessment=str(d.get("timing_assessment", "")),
            reason=str(d.get("reason", "")),
            suggested_workflow_ids=[
                str(x) for x in (d.get("suggested_workflow_ids") or [])
            ],
        )


# ---------------------------------------------------------------------------
# OnboardingState
# ---------------------------------------------------------------------------


@dataclass
class OnboardingState:
    """Onboarding-welcome lifecycle + per-flow progress for one user."""

    welcomed: bool = False
    exploration_started_at: float = field(default_factory=time.time)
    distinct_features_seen: int = 0
    explore_gate_passed: bool = False
    workflow_progress: dict[str, WorkflowProgress] = field(default_factory=dict)
    last_step_in: StepInAssessment | None = None
    last_reasoned_at: float | None = None
    last_welcome_at: float | None = None
    proactive_support_count: int = 0

    # ── derived helpers ────────────────────────────────────────────────────

    @property
    def completed_workflow_ids(self) -> list[str]:
        return [
            wid
            for wid, wp in self.workflow_progress.items()
            if wp.status == WorkflowStatus.COMPLETED
        ]

    @property
    def in_progress_workflow_ids(self) -> list[str]:
        return [
            wid
            for wid, wp in self.workflow_progress.items()
            if wp.status == WorkflowStatus.IN_PROGRESS
        ]

    def outstanding_workflow_ids(self, plan_workflow_ids: list[str]) -> list[str]:
        """Plan ids that are not yet completed (preserves plan order)."""
        completed = set(self.completed_workflow_ids)
        return [wid for wid in plan_workflow_ids if wid not in completed]

    # ── mutations ──────────────────────────────────────────────────────────

    def upsert_workflow_progress(
        self,
        workflow_id: str,
        *,
        status: WorkflowStatus,
        confidence: float,
        evidence: str = "",
        now: float | None = None,
    ) -> WorkflowProgress:
        """Create or update the agent's belief about one flow."""
        now = now if now is not None else time.time()
        wp = self.workflow_progress.get(workflow_id)
        if wp is None:
            wp = WorkflowProgress(
                workflow_id=workflow_id, first_detected_at=now, last_evaluated_at=now
            )
            self.workflow_progress[workflow_id] = wp
        wp.status = status
        wp.confidence = _clamp(float(confidence), 0.0, 1.0)
        if evidence:
            wp.evidence = evidence
        wp.last_evaluated_at = now
        if status == WorkflowStatus.COMPLETED and wp.completed_at is None:
            wp.completed_at = now
        return wp

    def record_step_in(self, assessment: StepInAssessment) -> None:
        self.last_step_in = assessment
        self.last_reasoned_at = assessment.decided_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "welcomed": self.welcomed,
            "exploration_started_at": self.exploration_started_at,
            "distinct_features_seen": self.distinct_features_seen,
            "explore_gate_passed": self.explore_gate_passed,
            "workflow_progress": {
                wid: wp.to_dict() for wid, wp in self.workflow_progress.items()
            },
            "last_step_in": (
                self.last_step_in.to_dict() if self.last_step_in else None
            ),
            "last_reasoned_at": self.last_reasoned_at,
            "last_welcome_at": self.last_welcome_at,
            "proactive_support_count": self.proactive_support_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> OnboardingState:
        d = d or {}
        raw_progress = d.get("workflow_progress") or {}
        progress: dict[str, WorkflowProgress] = {}
        if isinstance(raw_progress, dict):
            for wid, wp_raw in raw_progress.items():
                if isinstance(wp_raw, dict):
                    progress[str(wid)] = WorkflowProgress.from_dict(wp_raw)
        return cls(
            welcomed=bool(d.get("welcomed", False)),
            exploration_started_at=d.get("exploration_started_at", time.time()),
            distinct_features_seen=int(d.get("distinct_features_seen", 0)),
            explore_gate_passed=bool(d.get("explore_gate_passed", False)),
            workflow_progress=progress,
            last_step_in=StepInAssessment.from_dict(d.get("last_step_in")),
            last_reasoned_at=d.get("last_reasoned_at"),
            last_welcome_at=d.get("last_welcome_at"),
            proactive_support_count=int(d.get("proactive_support_count", 0)),
        )


# ---------------------------------------------------------------------------
# UserAdoptionState (top level)
# ---------------------------------------------------------------------------


@dataclass
class UserAdoptionState:
    """Top-level per-user adoption record.

    ``user_id`` is the only mandatory scope key (raises if empty, like
    ``SessionState``). ``metadata`` is a fully dynamic JSON-serialisable bag.
    """

    user_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    journey_state: JourneyState = JourneyState.ONBOARDING
    mastery: Mastery = field(default_factory=Mastery)
    discovered_features: list[str] = field(default_factory=list)
    onboarding: OnboardingState = field(default_factory=OnboardingState)
    first_seen_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    last_judged_at: float | None = None

    _v: int = _SNAPSHOT_VERSION

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError(
                "UserAdoptionState requires a non-empty user_id. "
                "Use: UserAdoptionState(user_id=your_id)"
            )

    # ── convenience ──────────────────────────────────────────────────────────

    @property
    def role(self) -> str | None:
        """Thin convenience accessor for the conventional ``role`` metadata key.

        ``role`` is not special-cased in storage; it is just one conventional
        key the onboarding gate reads.
        """
        role = self.metadata.get("role")
        return str(role) if role is not None else None

    # ── mutations (each logs a structured event) ─────────────────────────────

    def _touch(self) -> None:
        self.last_updated_at = time.time()

    def set_journey_state(self, new_state: JourneyState, *, reason: str = "") -> None:
        if new_state == self.journey_state:
            return
        logger.info(
            "user_adoption_state: user=%s journey %s -> %s (%s)",
            self.user_id,
            self.journey_state.value,
            new_state.value,
            reason,
            extra={"event_type": "adoption_journey_transition"},
        )
        self.journey_state = new_state
        self._touch()

    def set_mastery(
        self, *, rating: int, level: MasteryLevel, description: str = ""
    ) -> None:
        clamped = int(_clamp(float(rating), 0, 10))
        logger.info(
            "user_adoption_state: user=%s mastery rating=%d level=%s",
            self.user_id,
            clamped,
            level.value,
            extra={"event_type": "adoption_mastery_set"},
        )
        self.mastery = Mastery(rating=clamped, level=level, description=description)
        self._touch()

    def record_discovered_features(self, features: list[str]) -> None:
        added = False
        for f in features:
            f = (f or "").strip()
            if f and f not in self.discovered_features:
                self.discovered_features.append(f)
                added = True
        if added:
            self._touch()

    def mark_welcomed(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.onboarding.welcomed = True
        self.onboarding.last_welcome_at = now
        self.onboarding.proactive_support_count += 1
        self._touch()

    def mark_judged(self, *, now: float | None = None) -> None:
        self.last_judged_at = now if now is not None else time.time()
        self._touch()

    # ── persistence ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "_v": self._v,
            "user_id": self.user_id,
            "metadata": self.metadata,
            "journey_state": self.journey_state.value,
            "mastery": self.mastery.to_dict(),
            "discovered_features": list(self.discovered_features),
            "onboarding": self.onboarding.to_dict(),
            "first_seen_at": self.first_seen_at,
            "last_updated_at": self.last_updated_at,
            "last_judged_at": self.last_judged_at,
        }

    def to_prompt_block(self) -> str:
        """Render a compact ``[USER ADOPTION STATE]`` block for prompt injection.

        Intended to be prepended to the chat user block so the assistant can
        adapt depth: more teaching during onboarding, lighter touch for power
        users. Safe to call at any time; never raises.
        """
        guidance = (
            "favor step-by-step teaching and confirm basics"
            if self.journey_state == JourneyState.ONBOARDING
            else "be concise; skip basics unless asked"
        )
        role = self.role or "unknown"
        lines = [
            "[USER ADOPTION STATE]",
            f"role: {role}",
            f"journey: {self.journey_state.value}",
            f"mastery: {self.mastery.level.value} ({self.mastery.rating}/10)",
            f"guidance: {guidance}",
        ]
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserAdoptionState:
        if d.get("_v") != _SNAPSHOT_VERSION:
            logger.warning(
                "user_adoption_state: unknown snapshot version %r — cannot restore",
                d.get("_v"),
                extra={"event_type": "adoption_snapshot_invalid"},
            )
            raise ValueError(
                f"Unknown UserAdoptionState snapshot version: {d.get('_v')!r}"
            )
        try:
            journey = JourneyState(
                d.get("journey_state", JourneyState.ONBOARDING.value)
            )
        except ValueError:
            journey = JourneyState.ONBOARDING
        s = cls.__new__(cls)
        s._v = _SNAPSHOT_VERSION
        s.user_id = str(d.get("user_id", ""))
        if not s.user_id:
            logger.warning(
                "user_adoption_state: from_dict loaded snapshot with empty user_id",
                extra={"event_type": "adoption_snapshot_invalid"},
            )
        s.metadata = d.get("metadata") or {}
        s.journey_state = journey
        s.mastery = Mastery.from_dict(d.get("mastery"))
        s.discovered_features = [str(x) for x in (d.get("discovered_features") or [])]
        s.onboarding = OnboardingState.from_dict(d.get("onboarding"))
        s.first_seen_at = d.get("first_seen_at", time.time())
        s.last_updated_at = d.get("last_updated_at", time.time())
        s.last_judged_at = d.get("last_judged_at")
        return s
