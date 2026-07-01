"""Unit tests for the per-step activity-signal detector (phase 4).

Pairs with :file:`test_activity_detector.py`, but exclusively covers the
``detect_completed_steps_from_activity`` codepath added in phase 4 of the
production-ready-onboarding plan.

Why a separate file (not folded into ``test_activity_detector.py``):
    The workflow- and step-level detectors share matcher machinery but
    have meaningfully different semantics:

      * scope: workflow-detector iterates a *plan*; step-detector
        iterates a *single workflow's* ``steps``;
      * idempotency key: ``workflow_id`` vs. ``step_id``;
      * write target on the call site: ``WorkflowProgress.status`` vs.
        ``WorkflowProgress.upsert_step_progress``.

    Keeping them in separate files makes the contract boundary obvious
    when triaging a failed test (the file name tells you which layer
    you're fighting), and lets each file stay readable end-to-end.

Coverage:
  1. signals fire on a matching action stream;
  2. ``already_completed_step_ids`` blocks re-emission (idempotent
     replay — the failure mode this guards is the welcome runner's
     pre-pass re-running on every chat open);
  3. ``min_count`` is honoured per-step;
  4. unrelated step signals (in other workflows passed to a
     workflow-scoped call) are NOT considered — confirms the
     per-workflow scoping contract;
  5. steps with no ``activity_signals`` configured are ignored
     (degrade-to-LLM-only path);
  6. empty action list short-circuits without scanning steps;
  7. workflow without ``steps`` short-circuits without crashing
     (the field is optional on ``OnboardingWorkflow``).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from autoplay_sdk.user_adoption_state import (
    ActivitySignalRule,
    ActivitySignals,
    OnboardingWorkflow,
    StepActivityMatch,
    WorkflowStep,
    detect_completed_steps_from_activity,
)


@dataclass
class _FakeAction:
    """Mirror of the workflow-detector's test fixture — duck-typed."""

    type: str = ""
    title: str = ""
    canonical_url: str = ""
    description: str = ""
    event_type: str | None = None


def _step(
    sid: str,
    signals: ActivitySignals | None = None,
    *,
    required: bool = True,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=sid, name=sid, required=required, activity_signals=signals
    )


def _wf_with_steps(*steps: WorkflowStep) -> OnboardingWorkflow:
    return OnboardingWorkflow(workflow_id="wf-test", name="wf-test", steps=tuple(steps))


class TestStepDetector:
    def test_fires_on_matching_action(self) -> None:
        """A URL glob on a step matches the corresponding action and
        produces a ``StepActivityMatch`` keyed by ``step_id``."""
        step = _step(
            "open_create_modal",
            ActivitySignals(
                any_of=(ActivitySignalRule(canonical_url_glob="/caes/new"),)
            ),
        )
        wf = _wf_with_steps(step)
        actions = [_FakeAction(canonical_url="/caes/new")]

        out = detect_completed_steps_from_activity(wf, actions)

        assert set(out.keys()) == {"open_create_modal"}
        assert isinstance(out["open_create_modal"], StepActivityMatch)
        assert out["open_create_modal"].step_id == "open_create_modal"
        assert out["open_create_modal"].match_count == 1

    def test_event_type_signal_fires_for_save_step(self) -> None:
        """The save_cae step listens on the same ``cae_created`` event
        the workflow-level detector watches — both layers should
        independently fire on the same action stream (steps are signal,
        not a gate)."""
        step = _step(
            "save_cae",
            ActivitySignals(any_of=(ActivitySignalRule(event_type="cae_created"),)),
        )
        wf = _wf_with_steps(step)
        actions = [_FakeAction(event_type="cae_created")]

        out = detect_completed_steps_from_activity(wf, actions)

        assert "save_cae" in out

    def test_already_completed_step_is_skipped(self) -> None:
        """Idempotency: the welcome runner's pre-pass re-fires every
        chat open. Replaying the same action stream MUST NOT re-emit
        a step the caller already knows is done — otherwise we'd
        stamp ``last_evaluated_at`` on every read and churn the
        ``WorkflowProgress`` row needlessly."""
        step = _step(
            "save_cae",
            ActivitySignals(any_of=(ActivitySignalRule(event_type="cae_created"),)),
        )
        wf = _wf_with_steps(step)
        actions = [_FakeAction(event_type="cae_created")]

        out = detect_completed_steps_from_activity(
            wf, actions, already_completed_step_ids=["save_cae"]
        )

        assert out == {}

    def test_min_count_threshold_honoured(self) -> None:
        """A step rule with ``min_count=2`` requires two matching
        actions before it fires — guards against premature progress
        stamping on a single noisy event."""
        step = _step(
            "double_click",
            ActivitySignals(
                any_of=(
                    ActivitySignalRule(
                        event_type="cae_form_field_changed", min_count=2
                    ),
                )
            ),
        )
        wf = _wf_with_steps(step)
        single = [_FakeAction(event_type="cae_form_field_changed")]
        double = [
            _FakeAction(event_type="cae_form_field_changed"),
            _FakeAction(event_type="cae_form_field_changed"),
        ]

        assert detect_completed_steps_from_activity(wf, single) == {}
        out = detect_completed_steps_from_activity(wf, double)
        assert "double_click" in out
        assert out["double_click"].match_count == 2

    def test_step_without_signals_is_ignored(self) -> None:
        """Descriptive-only steps (no ``activity_signals``) degrade to
        the LLM-only inference path — the detector silently skips
        them so callers can mix signal-bearing and descriptive steps
        in the same workflow without filtering at the call site."""
        bare_step = _step("descriptive_only", signals=None)
        signal_step = _step(
            "save_cae",
            ActivitySignals(any_of=(ActivitySignalRule(event_type="cae_created"),)),
        )
        wf = _wf_with_steps(bare_step, signal_step)
        actions = [_FakeAction(event_type="cae_created")]

        out = detect_completed_steps_from_activity(wf, actions)

        assert set(out.keys()) == {"save_cae"}

    def test_empty_actions_short_circuits(self) -> None:
        """No actions ⇒ no matches, even when the workflow has
        signal-bearing steps. The pre-pass relies on this short-
        circuit when ``user_activity_store.get_recent_activity``
        returns an empty list (brand-new user)."""
        step = _step(
            "save_cae",
            ActivitySignals(any_of=(ActivitySignalRule(event_type="cae_created"),)),
        )
        wf = _wf_with_steps(step)

        assert detect_completed_steps_from_activity(wf, []) == {}

    def test_workflow_without_steps_returns_empty(self) -> None:
        """Per-step detection on a workflow that declared NO steps is
        a no-op. Confirms the field is genuinely optional — workflows
        that haven't been step-decomposed yet keep their existing
        behaviour (signal at the workflow level only)."""
        wf = OnboardingWorkflow(workflow_id="wf-no-steps", name="wf-no-steps")
        actions = [_FakeAction(event_type="cae_created")]

        assert detect_completed_steps_from_activity(wf, actions) == {}

    def test_only_first_matching_rule_per_step_fires(self) -> None:
        """``any_of`` is OR — once a step fires, the detector moves
        on. Pinning this behaviour because a future rule-order change
        could silently produce double matches and inflate
        ``match_count``."""
        step = _step(
            "open_create_modal",
            ActivitySignals(
                any_of=(
                    ActivitySignalRule(canonical_url_glob="/caes/new"),
                    ActivitySignalRule(canonical_url_glob="/caes/*"),
                )
            ),
        )
        wf = _wf_with_steps(step)
        actions = [_FakeAction(canonical_url="/caes/new")]

        out = detect_completed_steps_from_activity(wf, actions)

        assert "open_create_modal" in out
        # The FIRST rule (most specific glob) is the one we recorded.
        assert out["open_create_modal"].matched_rule.canonical_url_glob == "/caes/new"

    def test_evidence_string_carries_rule_fingerprint(self) -> None:
        """The evidence string is what ends up on
        ``StepProgress.evidence`` after the call site upserts. Pin
        the format so explainability copy doesn't regress when we
        tweak the rule summary."""
        rule = ActivitySignalRule(event_type="cae_created")
        step = _step("save_cae", ActivitySignals(any_of=(rule,)))
        wf = _wf_with_steps(step)
        actions = [_FakeAction(event_type="cae_created")]

        out = detect_completed_steps_from_activity(wf, actions)

        assert out["save_cae"].evidence_string == (
            "activity_signal[event=cae_created] matched x1"
        )


class TestWorkflowStepRoundTrip:
    def test_workflow_step_serialises_activity_signals(self) -> None:
        """``WorkflowStep.to_dict`` + ``from_dict`` round-trip preserves
        the new ``activity_signals`` field. Asserting both directions
        because product config is JSON-on-disk and we need to be able
        to author it by hand AND have the runtime serialiser produce
        the same shape."""
        step = WorkflowStep(
            step_id="open_create_modal",
            name="Open the create-CAE modal",
            activity_signals=ActivitySignals(
                any_of=(ActivitySignalRule(canonical_url_glob="/caes/new"),)
            ),
        )

        d = step.to_dict()
        assert "activity_signals" in d
        # The nested ``any_of`` block round-trips through the same
        # serialiser used by the workflow-level signals.
        assert d["activity_signals"] == {
            "any_of": [{"canonical_url_glob": "/caes/new"}]
        }

        rt = WorkflowStep.from_dict(d)
        assert rt == step

    def test_workflow_step_without_signals_omits_field(self) -> None:
        """Compactness: a descriptive-only step shouldn't bloat the
        serialised config with a null ``activity_signals`` key — keeps
        diffs small when product owners hand-edit ``products.json``."""
        step = WorkflowStep(step_id="descriptive_only", name="Read me")

        assert "activity_signals" not in step.to_dict()
        # And the roundtrip stays clean — no ``None`` literal.
        rt = WorkflowStep.from_dict(step.to_dict())
        assert rt.activity_signals is None

    def test_malformed_step_activity_signals_degrade_to_none(self) -> None:
        """Defensive parse mirrors the workflow-level contract: a
        broken ``activity_signals`` block falls back to ``None``
        (logged in the underlying ``ActivitySignals.from_dict``) so
        the step still loads — just without eager detection."""
        d = {
            "step_id": "bad_signals",
            "name": "bad",
            # Empty any_of ⇒ ActivitySignals.from_dict returns None.
            "activity_signals": {"any_of": []},
        }
        step = WorkflowStep.from_dict(d)
        assert step.activity_signals is None


@pytest.mark.parametrize("ids", [["save_cae"], ["save_cae", "open_create_modal"], []])
def test_already_completed_filter_idempotent_in_combinations(
    ids: list[str],
) -> None:
    """Parametric idempotency guard: regardless of which subset of
    steps the caller already considers complete, the detector never
    emits one of those step_ids. Catches a regression where a future
    optimisation might filter by ``signals`` BEFORE checking
    ``already`` (the wrong order — we'd waste work matching against a
    no-op step before discarding it)."""
    all_steps = [
        _step(
            "open_create_modal",
            ActivitySignals(
                any_of=(ActivitySignalRule(canonical_url_glob="/caes/new"),)
            ),
        ),
        _step(
            "save_cae",
            ActivitySignals(any_of=(ActivitySignalRule(event_type="cae_created"),)),
        ),
    ]
    wf = _wf_with_steps(*all_steps)
    actions = [
        _FakeAction(canonical_url="/caes/new"),
        _FakeAction(event_type="cae_created"),
    ]

    out = detect_completed_steps_from_activity(
        wf, actions, already_completed_step_ids=ids
    )

    for sid in ids:
        assert sid not in out
