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
import math
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

# Cap on the number of session envelopes kept inline in the (hot-read) user
# state document. The full history is never lost — every session is also
# persisted as its own frozen :class:`SessionSnapshot` key — but the index
# read on every session start stays bounded. ``UserAdoptionState.sessions_count``
# retains the true lifetime total even after the inline list is trimmed.
_MAX_SESSION_INDEX = 50

# Allowed values for ``SessionSnapshot.completion_rate_denominator`` — what the
# completion rate is measured against. Kept as plain ``str`` constants (not an
# Enum) to mirror the free-form ``WORKFLOW_PROGRESS_SOURCE_*`` convention and so
# new denominators can be added without an SDK release.
COMPLETION_RATE_DENOMINATOR_ALL_CATALOG = "all_catalog_workflows"
COMPLETION_RATE_DENOMINATOR_ASSIGNED = "assigned_workflows"
_COMPLETION_RATE_DENOMINATORS = frozenset(
    {COMPLETION_RATE_DENOMINATOR_ALL_CATALOG, COMPLETION_RATE_DENOMINATOR_ASSIGNED}
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Defensive coercion helpers (module-level so SessionSnapshot / SessionIndexEntry
# reuse the exact same hardening as OnboardingState / UserAdoptionState rather
# than re-deriving it). All guard against the string / null / NaN / ±Inf values
# a corrupt or hand-edited snapshot can carry — non-finite timestamps in
# particular silently break cooldown maths (``now - NaN`` comparisons are always
# False), so they are rejected here once.
# ---------------------------------------------------------------------------


def _finite_float(raw: Any, default: float) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _coerce_ts(raw: Any) -> float:
    """Coerce a timestamp to a finite float, defaulting to ``time.time()``."""
    return _finite_float(raw, time.time())


def _coerce_optional_ts(raw: Any) -> float | None:
    """Coerce a nullable timestamp; ``None`` for missing / non-finite values."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _non_negative_int(raw: Any) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, v)


def _str_list(raw: Any) -> list[str]:
    """Coerce an arbitrary value to a list of strings; non-iterables -> []."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x) for x in raw]


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
# StepProgress
# ---------------------------------------------------------------------------


@dataclass
class StepProgress:
    """The agent's evolving belief about one step within a workflow.

    A deliberate parallel to :class:`WorkflowProgress`, one level down: same
    ``status`` / ``confidence`` / ``evidence`` shape (drops ``first_detected_at``
    and swaps ``workflow_id`` -> ``step_id``). Steps are signal for the LLM and
    for explainability — they never gate workflow completion, which remains the
    LLM's holistic call on ``WorkflowProgress.status``.
    """

    step_id: str
    status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    confidence: float = 0.0
    evidence: str = ""
    completed_at: float | None = None
    last_evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "completed_at": self.completed_at,
            "last_evaluated_at": self.last_evaluated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepProgress:
        try:
            status = WorkflowStatus(d.get("status", WorkflowStatus.NOT_STARTED.value))
        except ValueError:
            status = WorkflowStatus.NOT_STARTED
        try:
            confidence = _clamp(float(d.get("confidence", 0.0)), 0.0, 1.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            step_id=str(d.get("step_id", "")),
            status=status,
            confidence=confidence,
            evidence=str(d.get("evidence", "")),
            completed_at=d.get("completed_at"),
            last_evaluated_at=d.get("last_evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# WorkflowProgress
# ---------------------------------------------------------------------------


# Allowed values for ``WorkflowProgress.source`` — the channel that last
# wrote this workflow's status. Free-form ``str`` rather than a closed
# Enum so future writers (e.g. an admin reset endpoint, an SDK
# consumer's bespoke detector) can label themselves without an SDK
# release. Convention enforced at write sites; readers (the welcome
# prompt's copy variation) treat unknown values like ``"unknown"``.
WORKFLOW_PROGRESS_SOURCE_TOUR = "tour"
WORKFLOW_PROGRESS_SOURCE_ACTIVITY = "activity"
WORKFLOW_PROGRESS_SOURCE_JUDGE = "judge"
WORKFLOW_PROGRESS_SOURCE_FOLLOWUP = "followup"
WORKFLOW_PROGRESS_SOURCE_MANUAL = "manual"
WORKFLOW_PROGRESS_SOURCE_UNKNOWN = "unknown"


@dataclass
class WorkflowProgress:
    """The agent's evolving belief about one target onboarding flow.

    The agent updates this over time as more live activity streams in. Keeping
    ``confidence`` + ``evidence`` + ``source`` makes the decision
    explainable, debuggable, and amenable to per-channel prompt copy
    variation ("nice work creating your CAE!" for ``activity`` vs
    "great work on the tour!" for ``tour``).

    ``steps`` holds per-step beliefs (keyed by ``step_id``) for the workflow's
    declared steps. They enrich the LLM's reasoning and make progress
    explainable, but do NOT gate completion — ``status`` remains the
    authoritative completion signal.
    """

    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    confidence: float = 0.0
    evidence: str = ""
    # The channel that last wrote this status. Defaults to ``"unknown"``
    # so legacy snapshots (pre-source field) round-trip without losing
    # their semantic meaning to "tour" — we'd rather mislabel as
    # unknown than wrongly claim a tour completion that never happened.
    source: str = WORKFLOW_PROGRESS_SOURCE_UNKNOWN
    first_detected_at: float | None = None
    completed_at: float | None = None
    last_evaluated_at: float = field(default_factory=time.time)
    steps: dict[str, StepProgress] = field(default_factory=dict)

    @property
    def completed_step_ids(self) -> list[str]:
        return [
            sid
            for sid, sp in self.steps.items()
            if sp.status == WorkflowStatus.COMPLETED
        ]

    def upsert_step_progress(
        self,
        step_id: str,
        *,
        status: WorkflowStatus,
        confidence: float,
        evidence: str = "",
        now: float | None = None,
    ) -> StepProgress:
        """Create or update the agent's belief about one step of this workflow.

        Mirrors :meth:`OnboardingState.upsert_workflow_progress`: stamps
        ``completed_at`` exactly once, the first time the step reaches
        ``COMPLETED``.
        """
        now = now if now is not None else time.time()
        sp = self.steps.get(step_id)
        if sp is None:
            sp = StepProgress(step_id=step_id, last_evaluated_at=now)
            self.steps[step_id] = sp
        sp.status = status
        sp.confidence = _clamp(float(confidence), 0.0, 1.0)
        if evidence:
            sp.evidence = evidence
        sp.last_evaluated_at = now
        if status == WorkflowStatus.COMPLETED and sp.completed_at is None:
            sp.completed_at = now
        return sp

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source": self.source,
            "first_detected_at": self.first_detected_at,
            "completed_at": self.completed_at,
            "last_evaluated_at": self.last_evaluated_at,
            "steps": {sid: sp.to_dict() for sid, sp in self.steps.items()},
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
        raw_steps = d.get("steps") or {}
        steps: dict[str, StepProgress] = {}
        if isinstance(raw_steps, dict):
            for sid, sp_raw in raw_steps.items():
                if isinstance(sp_raw, dict):
                    steps[str(sid)] = StepProgress.from_dict(sp_raw)
        # Coerce/normalise source: strings only, fall back to "unknown"
        # for legacy snapshots or malformed values.
        raw_source = d.get("source")
        source = (
            raw_source.strip()
            if isinstance(raw_source, str) and raw_source.strip()
            else WORKFLOW_PROGRESS_SOURCE_UNKNOWN
        )
        return cls(
            workflow_id=str(d.get("workflow_id", "")),
            status=status,
            confidence=confidence,
            evidence=str(d.get("evidence", "")),
            source=source,
            first_detected_at=d.get("first_detected_at"),
            completed_at=d.get("completed_at"),
            last_evaluated_at=d.get("last_evaluated_at", time.time()),
            steps=steps,
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
    # Timestamp the FIRST time this user finished every workflow required
    # by their role's plan. Set once and never cleared — even if a future
    # plan version adds new required workflows, we keep this stamped so
    # the chat doesn't keep re-engaging a user who already went through
    # the onboarding flow once. Proactive triggers (stuck-detection,
    # idle-recovery) remain active and unaffected by this flag.
    #
    # Caller-driven: set by ``mark_onboarding_complete`` from either the
    # tour-completion event handler (the live path) or the welcome runner
    # (the lazy-backfill path for users who completed before this field
    # shipped). ``None`` means "not yet complete" OR "complete but pre-
    # backfill" — the welcome runner treats both the same way.
    onboarding_completed_at: float | None = None

    # LLM-generated cross-session briefing, refreshed at session end. Read by
    # the agent at the next session start (injected via ``build_agent_context``).
    # ``None`` until a summary has ever been produced. The SDK never writes this
    # itself — it is supplied by the integration's summarizer.
    summary: str | None = None

    # Snapshot of onboarding completion (0.0-1.0) at the last session end. A
    # cached convenience copy of the most recent ``SessionSnapshot.completion_rate``
    # so the hot user-state read doesn't need to load a session document.
    completion_rate: float = 0.0

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
        source: str | None = None,
        now: float | None = None,
    ) -> WorkflowProgress:
        """Create or update the agent's belief about one flow.

        ``source`` records the channel that wrote this status — see the
        ``WORKFLOW_PROGRESS_SOURCE_*`` constants. Pass ``None`` (the
        default) to preserve the existing source when re-stamping a
        workflow you don't own; passing an explicit value overwrites
        it. The "preserve" behaviour matters for the welcome-runner
        pre-pass case: it re-stamps already-completed workflows on
        every welcome call as a safety net, and we don't want those
        defensive stamps to overwrite an authoritative "tour" source
        with a generic "judge" or "activity" label.

        Idempotent on (workflow_id, status, source) — re-writing the
        same triple is a no-op timestamp refresh, never a regression.
        """
        now = now if now is not None else time.time()
        wp = self.workflow_progress.get(workflow_id)
        if wp is None:
            wp = WorkflowProgress(
                workflow_id=workflow_id,
                first_detected_at=now,
                last_evaluated_at=now,
                # New entries get the explicit source if supplied,
                # otherwise the "unknown" default keeps the field
                # honest about provenance.
                source=source or WORKFLOW_PROGRESS_SOURCE_UNKNOWN,
            )
            self.workflow_progress[workflow_id] = wp
        wp.status = status
        wp.confidence = _clamp(float(confidence), 0.0, 1.0)
        if evidence:
            wp.evidence = evidence
        if source:
            wp.source = source
        wp.last_evaluated_at = now
        if status == WorkflowStatus.COMPLETED and wp.completed_at is None:
            wp.completed_at = now
        return wp

    def record_step_in(self, assessment: StepInAssessment) -> None:
        self.last_step_in = assessment
        self.last_reasoned_at = assessment.decided_at

    @property
    def is_onboarding_complete(self) -> bool:
        """True iff ``mark_onboarding_complete`` has ever been called."""
        return self.onboarding_completed_at is not None

    def mark_onboarding_complete(self, *, now: float | None = None) -> bool:
        """Stamp the user as having finished onboarding once and only once.

        Returns ``True`` if the stamp was newly set, ``False`` if it was
        already set (idempotent — callers can fire it on every workflow
        completion without worrying about double-stamping).

        We deliberately do NOT clear this on re-evaluation. Once a user
        has been through the onboarding loop they're done with it for
        good; the proactive-trigger path is the right channel to nudge
        them after that point, not the onboarding welcome.
        """
        if self.onboarding_completed_at is not None:
            return False
        self.onboarding_completed_at = now if now is not None else time.time()
        return True

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
            "onboarding_completed_at": self.onboarding_completed_at,
            "summary": self.summary,
            "completion_rate": self.completion_rate,
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

        # All timestamp fields are stored as floats but could be string /
        # null / NaN / ±Inf in a corrupt or hand-edited snapshot.
        # Welcome-time arithmetic (e.g. ``now - exploration_started_at``
        # in the gate) crashes with ``TypeError`` on a string, but more
        # subtly ``now - NaN == NaN`` which silently bypasses cooldowns
        # because every comparison against NaN is False — coerce
        # defensively and reject non-finite values.
        def _as_float_or_now(raw: Any) -> float:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return time.time()
            return v if math.isfinite(v) else time.time()

        def _as_optional_float(raw: Any) -> float | None:
            if raw is None:
                return None
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return None
            # Non-finite timestamps (NaN / ±Inf) can quietly bypass
            # welcome cooldown checks — every ``now - NaN < cooldown_s``
            # is False, so the gate would fire on every call. Treat
            # non-finite as "unknown" and let the caller's default apply.
            return v if math.isfinite(v) else None

        def _as_non_negative_int(raw: Any) -> int:
            try:
                v = int(raw)
            except (TypeError, ValueError):
                return 0
            return max(0, v)

        return cls(
            welcomed=bool(d.get("welcomed", False)),
            exploration_started_at=_as_float_or_now(d.get("exploration_started_at")),
            distinct_features_seen=_as_non_negative_int(
                d.get("distinct_features_seen", 0)
            ),
            explore_gate_passed=bool(d.get("explore_gate_passed", False)),
            workflow_progress=progress,
            last_step_in=StepInAssessment.from_dict(d.get("last_step_in")),
            last_reasoned_at=_as_optional_float(d.get("last_reasoned_at")),
            last_welcome_at=_as_optional_float(d.get("last_welcome_at")),
            proactive_support_count=_as_non_negative_int(
                d.get("proactive_support_count", 0)
            ),
            onboarding_completed_at=_as_optional_float(
                d.get("onboarding_completed_at")
            ),
            summary=(str(d["summary"]) if d.get("summary") is not None else None),
            completion_rate=_clamp(
                _finite_float(d.get("completion_rate"), 0.0), 0.0, 1.0
            ),
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

    # ── sessions ─────────────────────────────────────────────────────────────
    # Cross-session bookkeeping. ``sessions_count`` is the monotonic lifetime
    # total (never trimmed); ``current_session_id`` is the open session set at
    # session start; ``sessions_index`` is a bounded list of lightweight
    # envelopes for the most recent sessions (see ``record_session`` /
    # ``_MAX_SESSION_INDEX``). Full per-session detail lives in separate frozen
    # ``SessionSnapshot`` documents, never here.
    sessions_count: int = 0
    current_session_id: str | None = None
    sessions_index: list[SessionIndexEntry] = field(default_factory=list)

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

    def set_current_session(self, session_id: str) -> None:
        """Mark ``session_id`` as the user's currently-open session."""
        self.current_session_id = (session_id or "").strip() or None
        self._touch()

    def record_session(self, entry: SessionIndexEntry) -> None:
        """Append a finished session's envelope to the index and bump the count.

        ``sessions_count`` is the true lifetime total and is never trimmed. The
        inline ``sessions_index`` is capped to the most recent
        ``_MAX_SESSION_INDEX`` envelopes so the hot session-start read stays
        bounded; older sessions remain fully retrievable via their own
        ``SessionSnapshot`` key.
        """
        self.sessions_count += 1
        self.sessions_index.append(entry)
        if len(self.sessions_index) > _MAX_SESSION_INDEX:
            del self.sessions_index[:-_MAX_SESSION_INDEX]
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
            "sessions": {
                "count": self.sessions_count,
                "current_session_id": self.current_session_id,
                "index": [e.to_dict() for e in self.sessions_index],
            },
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
        # ``metadata`` is a free-form bag but downstream code (e.g. the
        # ``role`` accessor) assumes it's a dict. A corrupt snapshot with
        # a list / string / null would otherwise raise on the first
        # ``metadata.get(...)`` call — defend at deserialisation.
        meta_raw = d.get("metadata")
        s.metadata = meta_raw if isinstance(meta_raw, dict) else {}
        s.journey_state = journey
        s.mastery = Mastery.from_dict(d.get("mastery"))
        s.discovered_features = [str(x) for x in (d.get("discovered_features") or [])]
        s.onboarding = OnboardingState.from_dict(d.get("onboarding"))

        # Same defensive coercion as ``OnboardingState.from_dict``: a
        # corrupt snapshot must not be able to crash the gate or judge
        # via downstream arithmetic on string / null / NaN / ±Inf
        # timestamps. Non-finite values are particularly dangerous
        # because they pass ``float(...)`` silently and then break
        # cooldown maths (``now - last_judged_at < cooldown`` is False
        # for any non-finite ``last_judged_at``).
        def _coerce_ts(raw: Any) -> float:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return time.time()
            return v if math.isfinite(v) else time.time()

        def _coerce_optional_ts(raw: Any) -> float | None:
            if raw is None:
                return None
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return None
            return v if math.isfinite(v) else None

        s.first_seen_at = _coerce_ts(d.get("first_seen_at"))
        s.last_updated_at = _coerce_ts(d.get("last_updated_at"))
        s.last_judged_at = _coerce_optional_ts(d.get("last_judged_at"))

        # ``sessions`` is a nested envelope; a corrupt snapshot may carry a
        # non-dict here, so default defensively to an empty mapping.
        sessions_raw = d.get("sessions")
        sessions = sessions_raw if isinstance(sessions_raw, dict) else {}
        s.sessions_count = _non_negative_int(sessions.get("count", 0))
        current = sessions.get("current_session_id")
        s.current_session_id = str(current) if current else None
        raw_index = sessions.get("index")
        index: list[SessionIndexEntry] = []
        if isinstance(raw_index, (list, tuple)):
            for entry in raw_index:
                if isinstance(entry, dict):
                    index.append(SessionIndexEntry.from_dict(entry))
        # Defend the inline cap even on load, in case an externally-written
        # snapshot exceeded it.
        if len(index) > _MAX_SESSION_INDEX:
            index = index[-_MAX_SESSION_INDEX:]
        s.sessions_index = index
        return s


# ---------------------------------------------------------------------------
# SessionIndexEntry
# ---------------------------------------------------------------------------


@dataclass
class SessionIndexEntry:
    """A lightweight pointer to one finished session held in the user state.

    Deliberately just the envelope (ids + timestamps) — no workflow detail, no
    mastery — so the per-session-start read of :class:`UserAdoptionState` stays
    cheap. Full per-session data lives in the matching :class:`SessionSnapshot`
    document, addressable by ``session_id``.
    """

    session_id: str
    session_number: int
    started_at: float
    captured_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_number": self.session_number,
            "started_at": self.started_at,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionIndexEntry:
        return cls(
            session_id=str(d.get("session_id", "")),
            session_number=_non_negative_int(d.get("session_number", 0)),
            started_at=_coerce_ts(d.get("started_at")),
            captured_at=_coerce_ts(d.get("captured_at")),
        )


# ---------------------------------------------------------------------------
# SessionSnapshot (frozen, write-once per session)
# ---------------------------------------------------------------------------


@dataclass
class SessionSnapshot:
    """A frozen, point-in-time capture of one session, written once at its end.

    Unlike :class:`UserAdoptionState` (mutable, overwritten each session), a
    snapshot is immutable: persisted write-once (``SET NX``) and never updated.
    The per-user series of snapshots is the durable history the agent reasons
    over across sessions.

    ``workflow_progress`` reuses :class:`WorkflowProgress` rather than a parallel
    near-identical type — the snapshot is a deep copy of the user's beliefs at
    capture time.
    """

    session_id: str
    session_number: int
    user_id: str
    started_at: float
    captured_at: float = field(default_factory=time.time)
    duration_s: float = 0.0
    journey_state: JourneyState = JourneyState.ONBOARDING
    mastery: Mastery = field(default_factory=Mastery)
    proactive_support_count: int = 0
    distinct_features_seen: int = 0
    discovered_features: list[str] = field(default_factory=list)
    reached_onboarding_complete: bool = False
    completion_rate: float = 0.0
    completion_rate_denominator: str = COMPLETION_RATE_DENOMINATOR_ALL_CATALOG
    total_catalog_workflows: int = 0
    completed_workflow_ids: list[str] = field(default_factory=list)
    in_progress_workflow_ids: list[str] = field(default_factory=list)
    untouched_workflow_ids: list[str] = field(default_factory=list)
    workflow_progress: dict[str, WorkflowProgress] = field(default_factory=dict)

    _frozen: bool = True
    _v: int = _SNAPSHOT_VERSION

    @classmethod
    def from_adoption_state(
        cls,
        state: UserAdoptionState,
        *,
        session_id: str,
        session_number: int,
        started_at: float,
        catalog_workflow_ids: list[str],
        completion_rate_denominator: str = COMPLETION_RATE_DENOMINATOR_ALL_CATALOG,
        now: float | None = None,
    ) -> SessionSnapshot:
        """Build a frozen snapshot from a live :class:`UserAdoptionState`.

        Reuses the model's own derived helpers (``completed_workflow_ids`` /
        ``in_progress_workflow_ids``) and the ``WorkflowStatus`` enum — there is
        no string-compare or hand-rolled mapping. ``untouched`` is the set of
        catalog workflows the user has no recorded belief about yet.

        Args:
            state: The user's current adoption state.
            session_id: Identifier for the session being captured.
            session_number: 1-based ordinal of this session for the user.
            started_at: Unix timestamp the session began.
            catalog_workflow_ids: All workflow ids in scope (drives ``untouched``
                and the completion-rate denominator).
            completion_rate_denominator: One of the
                ``COMPLETION_RATE_DENOMINATOR_*`` constants.
            now: Override for the capture time (tests); defaults to ``time.time()``.
        """
        now = now if now is not None else time.time()
        started = _finite_float(started_at, now)

        completed = state.onboarding.completed_workflow_ids
        in_progress = state.onboarding.in_progress_workflow_ids
        touched = set(state.onboarding.workflow_progress)
        catalog = [str(w) for w in catalog_workflow_ids]
        untouched = [wid for wid in catalog if wid not in touched]
        total = len(catalog)
        completion = round(len(completed) / total, 4) if total else 0.0

        # Deep-copy each WorkflowProgress through its own dict round-trip so the
        # frozen snapshot never aliases the live (still-mutating) state.
        frozen_progress = {
            wid: WorkflowProgress.from_dict(wp.to_dict())
            for wid, wp in state.onboarding.workflow_progress.items()
        }

        denominator = (
            completion_rate_denominator
            if completion_rate_denominator in _COMPLETION_RATE_DENOMINATORS
            else COMPLETION_RATE_DENOMINATOR_ALL_CATALOG
        )

        return cls(
            session_id=str(session_id),
            session_number=_non_negative_int(session_number),
            user_id=state.user_id,
            started_at=started,
            captured_at=now,
            duration_s=round(max(0.0, now - started), 2),
            journey_state=state.journey_state,
            mastery=Mastery(
                rating=state.mastery.rating,
                level=state.mastery.level,
                description=state.mastery.description,
            ),
            proactive_support_count=state.onboarding.proactive_support_count,
            distinct_features_seen=state.onboarding.distinct_features_seen,
            discovered_features=list(state.discovered_features),
            reached_onboarding_complete=state.onboarding.is_onboarding_complete,
            completion_rate=completion,
            completion_rate_denominator=denominator,
            total_catalog_workflows=total,
            completed_workflow_ids=list(completed),
            in_progress_workflow_ids=list(in_progress),
            untouched_workflow_ids=untouched,
            workflow_progress=frozen_progress,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "_v": self._v,
            "_frozen": self._frozen,
            "session_id": self.session_id,
            "session_number": self.session_number,
            "user_id": self.user_id,
            "started_at": self.started_at,
            "captured_at": self.captured_at,
            "duration_s": self.duration_s,
            "journey_state": self.journey_state.value,
            "mastery": self.mastery.to_dict(),
            "proactive_support_count": self.proactive_support_count,
            "distinct_features_seen": self.distinct_features_seen,
            "discovered_features": list(self.discovered_features),
            "reached_onboarding_complete": self.reached_onboarding_complete,
            "completion_rate": self.completion_rate,
            "completion_rate_denominator": self.completion_rate_denominator,
            "total_catalog_workflows": self.total_catalog_workflows,
            "completed_workflow_ids": list(self.completed_workflow_ids),
            "in_progress_workflow_ids": list(self.in_progress_workflow_ids),
            "untouched_workflow_ids": list(self.untouched_workflow_ids),
            "workflow_progress": {
                wid: wp.to_dict() for wid, wp in self.workflow_progress.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> SessionSnapshot:
        """Restore a snapshot, defensively coercing a corrupt/partial document.

        Lenient by design (no version raise): snapshots are write-once history,
        so degrading a malformed field to a safe default is preferable to
        refusing to load a frozen record.
        """
        d = d or {}
        try:
            journey = JourneyState(
                d.get("journey_state", JourneyState.ONBOARDING.value)
            )
        except ValueError:
            journey = JourneyState.ONBOARDING

        raw_progress = d.get("workflow_progress") or {}
        progress: dict[str, WorkflowProgress] = {}
        if isinstance(raw_progress, dict):
            for wid, wp_raw in raw_progress.items():
                if isinstance(wp_raw, dict):
                    progress[str(wid)] = WorkflowProgress.from_dict(wp_raw)

        denominator = d.get("completion_rate_denominator")
        if denominator not in _COMPLETION_RATE_DENOMINATORS:
            denominator = COMPLETION_RATE_DENOMINATOR_ALL_CATALOG

        return cls(
            session_id=str(d.get("session_id", "")),
            session_number=_non_negative_int(d.get("session_number", 0)),
            user_id=str(d.get("user_id", "")),
            started_at=_coerce_ts(d.get("started_at")),
            captured_at=_coerce_ts(d.get("captured_at")),
            duration_s=_finite_float(d.get("duration_s"), 0.0),
            journey_state=journey,
            mastery=Mastery.from_dict(d.get("mastery")),
            proactive_support_count=_non_negative_int(
                d.get("proactive_support_count", 0)
            ),
            distinct_features_seen=_non_negative_int(
                d.get("distinct_features_seen", 0)
            ),
            discovered_features=_str_list(d.get("discovered_features")),
            reached_onboarding_complete=bool(
                d.get("reached_onboarding_complete", False)
            ),
            completion_rate=_clamp(
                _finite_float(d.get("completion_rate"), 0.0), 0.0, 1.0
            ),
            completion_rate_denominator=denominator,
            total_catalog_workflows=_non_negative_int(
                d.get("total_catalog_workflows", 0)
            ),
            completed_workflow_ids=_str_list(d.get("completed_workflow_ids")),
            in_progress_workflow_ids=_str_list(d.get("in_progress_workflow_ids")),
            untouched_workflow_ids=_str_list(d.get("untouched_workflow_ids")),
            workflow_progress=progress,
            _frozen=bool(d.get("_frozen", True)),
        )
