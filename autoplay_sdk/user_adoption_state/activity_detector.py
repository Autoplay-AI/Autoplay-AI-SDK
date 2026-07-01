"""Pure, declarative activity-signal → workflow-completion detector.

Bridges raw `SlimAction` streams from the live-activity pipeline to the
deterministic side of `OnboardingState.workflow_progress`. The shape is
deliberately small: a workflow declares ``activity_signals`` in product
config, and this module's ``detect_completed_workflows_from_activity``
maps a recent action window to a set of newly-completed workflow ids.

Why a separate module (not folded into :mod:`onboarding_plan`):
    Detection logic depends on the ``SlimAction`` wire type from
    :mod:`autoplay_sdk.core.models`. ``onboarding_plan`` is otherwise
    leaf-level (no core-models import), and we want to keep it that way
    so consumers that only need the plan parser don't transitively pull
    in action types. Importing this module is opt-in.

Why pure (no I/O, no logging side effects in the hot path):
    The detector is called from two paths — the forwarder's per-batch
    fast path (latency-sensitive, ~1ms budget) and the welcome/followup
    runners' belt-and-suspenders pre-pass. Either path can fire dozens
    of times per second under load; pushing I/O or stateful logging
    into the detector itself would make it the system's bottleneck.
    Callers own observability (metrics, structured logs) on the way
    out.

Why explicit rule types (instead of arbitrary JSON predicates):
    Onboarding teams (not engineers) tune `activity_signals` blocks
    in production config. A closed-rule enum gives them a documented
    surface, lets us fail-fast on parse errors at startup (rather than
    at the first matching event), and keeps the hot-path matcher a
    sequence of branchy field comparisons rather than a generic
    expression interpreter.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Import the SlimAction type only for static checkers. We accept any
    # duck-typed object with the right attributes at runtime so callers
    # don't have to construct full SlimActions for tests (e.g. the
    # welcome-runner pre-pass works off a recent-actions cache that may
    # store a lighter projection).
    from autoplay_sdk.core.models import SlimAction  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule + config types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivitySignalRule:
    """One deterministic match rule against the live SlimAction stream.

    All non-None fields are AND'd within a single rule. A rule with
    multiple fields set means "an action must satisfy ALL of them to
    count toward `min_count`." OR semantics are expressed at the
    ActivitySignals level via ``any_of``.

    Why all-fields-optional + None as the "ignore me" sentinel: makes
    the JSON config compact and ergonomic — config writers only spell
    out the dimensions they care about. The runtime matcher just
    short-circuits on None for each unused field.

    Why ``description`` is intentionally NOT a matchable field:
        SlimAction.description can carry user-typed strings (search
        queries, form values). Letting state mutations be gated on
        free-form user content is a PII + reproducibility risk. Stick
        to schema-defined fields: ``type``, ``title``, ``canonical_url``,
        and ``event_type`` (the raw PostHog event name, when the caller
        chooses to expose it).
    """

    event_type: str | None = None
    canonical_url_glob: str | None = None
    canonical_url_prefix: str | None = None
    title_contains: str | None = None
    type: str | None = None
    min_count: int = 1

    def __post_init__(self) -> None:
        # An "empty" rule (no matchable fields) would otherwise silently
        # match EVERY action — a config typo (e.g. ``{"event_typo": ...}``)
        # would map every single page-view to workflow completion. Refuse
        # to construct such a rule so the failure surfaces at parse time
        # (in ActivitySignals.from_dict) instead of at the first event.
        has_match = any(
            v is not None
            for v in (
                self.event_type,
                self.canonical_url_glob,
                self.canonical_url_prefix,
                self.title_contains,
                self.type,
            )
        )
        if not has_match:
            raise ValueError(
                "ActivitySignalRule must specify at least one matchable "
                "field (event_type, canonical_url_glob, "
                "canonical_url_prefix, title_contains, or type)"
            )
        if self.min_count < 1:
            raise ValueError(
                f"ActivitySignalRule.min_count must be >= 1, got {self.min_count}"
            )

    def matches_action(self, action: Any) -> bool:
        """Return True iff ``action`` satisfies every set field on this rule.

        ``action`` is duck-typed for testability: any object with the
        relevant attributes works. Missing attributes are treated as
        empty strings so a partial action (e.g. only ``canonical_url``
        set) doesn't crash the matcher with AttributeError.
        """
        if self.event_type is not None:
            ev = _get_attr_or_key(action, "event_type") or _get_attr_or_key(
                action, "type"
            )
            if not isinstance(ev, str) or ev != self.event_type:
                return False

        if self.canonical_url_glob is not None:
            url = _get_attr_or_key(action, "canonical_url")
            if not isinstance(url, str) or not fnmatch.fnmatchcase(
                url, self.canonical_url_glob
            ):
                return False

        if self.canonical_url_prefix is not None:
            url = _get_attr_or_key(action, "canonical_url")
            if not isinstance(url, str) or not url.startswith(
                self.canonical_url_prefix
            ):
                return False

        if self.title_contains is not None:
            title = _get_attr_or_key(action, "title")
            if not isinstance(title, str):
                return False
            if self.title_contains.lower() not in title.lower():
                return False

        if self.type is not None:
            t = _get_attr_or_key(action, "type")
            if not isinstance(t, str) or t.lower() != self.type.lower():
                return False

        return True

    def summary(self) -> str:
        """Compact, human-readable describing the rule (for evidence strings)."""
        parts: list[str] = []
        if self.event_type is not None:
            parts.append(f"event={self.event_type}")
        if self.canonical_url_glob is not None:
            parts.append(f"url~{self.canonical_url_glob}")
        if self.canonical_url_prefix is not None:
            parts.append(f"url^{self.canonical_url_prefix}")
        if self.title_contains is not None:
            parts.append(f"title~{self.title_contains}")
        if self.type is not None:
            parts.append(f"type={self.type}")
        if self.min_count != 1:
            parts.append(f"x{self.min_count}")
        return ",".join(parts) or "<empty>"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActivitySignalRule:
        """Parse a raw config dict.

        Defensive coercion: rejects empty/whitespace-only matchable
        strings (which would behave the same as None and silently
        broaden the rule) by treating them as None. Raises
        ``ValueError`` via ``__post_init__`` if the resulting rule has
        no matchable fields.
        """

        def _norm(key: str) -> str | None:
            raw = d.get(key)
            if not isinstance(raw, str):
                return None
            s = raw.strip()
            return s or None

        min_count_raw = d.get("min_count", 1)
        try:
            min_count = max(1, int(min_count_raw))
        except (TypeError, ValueError):
            min_count = 1

        return cls(
            event_type=_norm("event_type"),
            canonical_url_glob=_norm("canonical_url_glob"),
            canonical_url_prefix=_norm("canonical_url_prefix"),
            title_contains=_norm("title_contains"),
            type=_norm("type"),
            min_count=min_count,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.event_type is not None:
            d["event_type"] = self.event_type
        if self.canonical_url_glob is not None:
            d["canonical_url_glob"] = self.canonical_url_glob
        if self.canonical_url_prefix is not None:
            d["canonical_url_prefix"] = self.canonical_url_prefix
        if self.title_contains is not None:
            d["title_contains"] = self.title_contains
        if self.type is not None:
            d["type"] = self.type
        if self.min_count != 1:
            d["min_count"] = self.min_count
        return d


@dataclass(frozen=True)
class ActivitySignals:
    """OR'd group of rules whose union marks a workflow as complete.

    Semantics: the workflow completes when AT LEAST ONE rule in
    ``any_of`` fires (matches ``>= min_count`` actions in the batch).
    The ``completion_threshold`` parameter is reserved for future
    "user must do N distinct things" semantics — kept here so we can
    grow into it without a config migration. Today the runtime fires
    on the first matching rule.

    Why not AND across rules: in practice the heuristics we want to
    express are alternatives ("user navigated to /caes/:id" OR
    "user submitted a Create CAE form") that capture the same
    intent through different signals. AND'd rules quickly produce
    deadlocks when one signal source is misbehaving.
    """

    any_of: tuple[ActivitySignalRule, ...] = ()
    completion_threshold: int = 1

    def __post_init__(self) -> None:
        if not self.any_of:
            raise ValueError(
                "ActivitySignals.any_of must be non-empty — otherwise the "
                "block can never fire and is just config noise"
            )
        if self.completion_threshold < 1:
            raise ValueError(
                "ActivitySignals.completion_threshold must be >= 1, got "
                f"{self.completion_threshold}"
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ActivitySignals | None:
        """Parse a raw config dict; returns ``None`` for missing/empty config.

        Per-rule parse errors short-circuit to ``None`` for the whole
        block (logged) so a single typo doesn't half-configure a
        workflow into a confusing partial state.
        """
        if not isinstance(d, dict):
            return None
        raw_any_of = d.get("any_of")
        if not isinstance(raw_any_of, list) or not raw_any_of:
            return None
        rules: list[ActivitySignalRule] = []
        for i, raw in enumerate(raw_any_of):
            if not isinstance(raw, dict):
                logger.warning(
                    "activity_signals: any_of[%d] is not a dict — skipping", i
                )
                continue
            try:
                rules.append(ActivitySignalRule.from_dict(raw))
            except ValueError as exc:
                logger.warning(
                    "activity_signals: any_of[%d] invalid (%s) — skipping rule",
                    i,
                    exc,
                )
        if not rules:
            return None
        threshold_raw = d.get("completion_threshold", 1)
        try:
            threshold = max(1, int(threshold_raw))
        except (TypeError, ValueError):
            threshold = 1
        return cls(any_of=tuple(rules), completion_threshold=threshold)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"any_of": [r.to_dict() for r in self.any_of]}
        if self.completion_threshold != 1:
            out["completion_threshold"] = self.completion_threshold
        return out


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityMatch:
    """Outcome of a successful detection for one workflow.

    Carried back to the caller so it can write a meaningful
    ``WorkflowProgress.evidence`` string and emit observability data.
    Intentionally lightweight — the matched actions themselves are NOT
    held here (they can contain user content; we already logged the
    rule fingerprint and the count).
    """

    workflow_id: str
    matched_rule: ActivitySignalRule
    match_count: int = 1
    rules_fired: int = 1

    @property
    def rule_summary(self) -> str:
        return self.matched_rule.summary()

    @property
    def evidence_string(self) -> str:
        """Format suitable for ``WorkflowProgress.evidence``."""
        return f"activity_signal[{self.rule_summary}] matched x{self.match_count}"


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


def detect_completed_workflows_from_activity(
    workflows: Iterable[Any],
    actions: Sequence[Any],
    already_completed: Iterable[str] = (),
) -> dict[str, ActivityMatch]:
    """Return ``{workflow_id: ActivityMatch}`` for newly-fired workflows.

    Args:
        workflows: Iterable of ``OnboardingWorkflow``-shaped objects.
            We duck-type on ``.workflow_id`` and ``.activity_signals``
            so callers can pass either a full :class:`OnboardingPlan`
            (its ``.workflows`` list) or a pre-filtered subset
            (e.g. role-scoped workflows from ``plan.for_role(...)``).
        actions: Sequence of ``SlimAction``-shaped objects (or any
            object exposing the matched fields as attributes or dict
            keys — see :meth:`ActivitySignalRule.matches_action`).
        already_completed: Workflow ids the caller already considers
            done — skipped (no match emitted) to keep this function
            idempotent. This is the primary mechanism for not
            re-stamping the same workflow on every batch.

    Returns:
        Dict of ``workflow_id -> ActivityMatch`` for workflows whose
        signals fired in this batch. Empty dict (NOT ``None``) when
        nothing matched — keeps caller call-sites branch-light
        (``if matches: ... for wid, m in matches.items(): ...``).

    Pure: no I/O, no logging beyond debug-level rule-fired traces.
    Safe to call from any context (sync or async).
    """
    already = {str(c).strip() for c in already_completed if str(c).strip()}
    out: dict[str, ActivityMatch] = {}
    if not actions:
        return out

    for wf in workflows:
        wid = getattr(wf, "workflow_id", None)
        if not isinstance(wid, str) or not wid:
            continue
        if wid in already:
            continue
        signals = getattr(wf, "activity_signals", None)
        if not isinstance(signals, ActivitySignals):
            continue

        # Evaluate each OR'd rule independently. The first rule that
        # reaches its min_count wins — we don't compare rule
        # specificities. Config authors implicitly order rules by
        # confidence by putting the strongest signal first.
        for rule in signals.any_of:
            count = 0
            for action in actions:
                if rule.matches_action(action):
                    count += 1
                    if count >= rule.min_count:
                        break
            if count >= rule.min_count:
                out[wid] = ActivityMatch(
                    workflow_id=wid,
                    matched_rule=rule,
                    match_count=count,
                    rules_fired=1,
                )
                break  # workflow done, no need to check remaining rules

    return out


@dataclass(frozen=True)
class StepActivityMatch:
    """Outcome of a successful per-step detection.

    Parallel to :class:`ActivityMatch` one level down: same rule
    fingerprint + count + evidence helper, scoped to a single
    ``step_id`` within a workflow. Kept separate (rather than
    overloading ``ActivityMatch.workflow_id`` with the step id) so
    callers can write each layer to the right place
    (``WorkflowProgress.status`` for workflows,
    ``WorkflowProgress.upsert_step_progress`` for steps) without
    runtime type-sniffing.
    """

    step_id: str
    matched_rule: ActivitySignalRule
    match_count: int = 1

    @property
    def rule_summary(self) -> str:
        return self.matched_rule.summary()

    @property
    def evidence_string(self) -> str:
        return f"activity_signal[{self.rule_summary}] matched x{self.match_count}"


def detect_completed_steps_from_activity(
    workflow: Any,
    actions: Sequence[Any],
    already_completed_step_ids: Iterable[str] = (),
) -> dict[str, StepActivityMatch]:
    """Return ``{step_id: StepActivityMatch}`` for steps newly fired by activity.

    Parallel to :func:`detect_completed_workflows_from_activity` one level down:
    runs the SAME rule-matching machinery against the workflow's per-step
    ``activity_signals`` blocks (added in this file's parent module's
    ``WorkflowStep``). Pure, side-effect-free, latency-cheap — same
    invariants as the workflow-level detector for the same reason
    (called from the per-batch fast path).

    Args:
        workflow: Any object exposing ``.steps`` as an iterable of
            ``WorkflowStep``-shaped objects (duck-typed on ``.step_id``
            and ``.activity_signals``). Pass a single workflow, NOT a
            plan — per-step signals are scoped within a workflow's
            id-space, and matching across workflows would let the same
            step_id collide. Callers wanting to fan this out across a
            plan iterate themselves (see the welcome-runner pre-pass).
        actions: Sequence of ``SlimAction``-shaped objects. Same
            duck-typing contract as the workflow-level detector.
        already_completed_step_ids: Step ids the caller already considers
            done — skipped to keep this function idempotent on retry.

    Returns:
        Dict of ``step_id -> StepActivityMatch`` for steps whose
        signals fired in this batch. Empty dict when nothing matched
        OR the workflow has no steps OR none of its steps declare
        ``activity_signals`` — callers shouldn't have to branch on
        "feature not configured" vs "no match".

    NOTE: this detector is fully decoupled from workflow-level
    completion. A workflow can be marked completed by its own
    ``activity_signals`` block in the same batch where zero of its
    steps fire individually — and vice-versa. Steps are signal for
    the LLM's per-step inference + the progress pill, NOT a gate.
    Workflow completion remains driven by
    :func:`detect_completed_workflows_from_activity` and the LLM
    judge, never by the union of step completions.
    """
    already = {str(s).strip() for s in already_completed_step_ids if str(s).strip()}
    out: dict[str, StepActivityMatch] = {}
    if not actions:
        return out

    steps_iter = getattr(workflow, "steps", None)
    if not steps_iter:
        return out

    for step in steps_iter:
        sid = getattr(step, "step_id", None)
        if not isinstance(sid, str) or not sid:
            continue
        if sid in already:
            continue
        signals = getattr(step, "activity_signals", None)
        if not isinstance(signals, ActivitySignals):
            continue

        # Same first-rule-wins ordering as the workflow detector — keeps
        # the per-step config ergonomic (write strongest signal first).
        for rule in signals.any_of:
            count = 0
            for action in actions:
                if rule.matches_action(action):
                    count += 1
                    if count >= rule.min_count:
                        break
            if count >= rule.min_count:
                out[sid] = StepActivityMatch(
                    step_id=sid,
                    matched_rule=rule,
                    match_count=count,
                )
                break  # step done, skip remaining rules

    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Read ``name`` from ``obj`` whether it's an attribute or a dict key.

    Lets the matcher work uniformly on ``SlimAction`` instances,
    dict-shaped projections from a Redis cache, or lightweight test
    fixtures. Missing attributes/keys return ``None`` (NOT an empty
    string) so the matcher can distinguish "field absent" from "field
    explicitly empty".
    """
    if obj is None:
        return None
    val = getattr(obj, name, _SENTINEL)
    if val is not _SENTINEL:
        return val
    if isinstance(obj, dict):
        return obj.get(name)
    return None


_SENTINEL: Any = object()
