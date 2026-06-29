"""Unit tests for the pure activity-signal → workflow-completion detector.

Covers:
  - rule construction (empty rule rejection, min_count validation)
  - parsing (round-trip, defensive coercion of malformed config)
  - matching semantics (single field, multi-field AND, OR via any_of)
  - min_count thresholds
  - duck-typed action shapes (SlimAction, dict, simple object)
  - idempotency via ``already_completed`` filter
  - PII safety: ``description`` is NOT a matchable field
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from autoplay_sdk.user_adoption_state import (
    ActivityMatch,
    ActivitySignalRule,
    ActivitySignals,
    OnboardingPlan,
    OnboardingWorkflow,
    detect_completed_workflows_from_activity,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeAction:
    """Test-only stand-in for SlimAction to avoid the core-models import."""

    type: str = ""
    title: str = ""
    canonical_url: str = ""
    description: str = ""
    event_type: str | None = None


def _wf(wid: str, signals: ActivitySignals | None = None) -> OnboardingWorkflow:
    return OnboardingWorkflow(workflow_id=wid, name=wid, activity_signals=signals)


# ---------------------------------------------------------------------------
# ActivitySignalRule construction + validation
# ---------------------------------------------------------------------------


class TestActivitySignalRuleConstruction:
    def test_rejects_rule_with_no_matchable_fields(self) -> None:
        with pytest.raises(ValueError, match="at least one matchable field"):
            ActivitySignalRule()

    def test_rejects_rule_with_min_count_zero(self) -> None:
        with pytest.raises(ValueError, match="min_count must be >= 1"):
            ActivitySignalRule(event_type="x", min_count=0)

    def test_rejects_rule_with_negative_min_count(self) -> None:
        with pytest.raises(ValueError, match="min_count must be >= 1"):
            ActivitySignalRule(event_type="x", min_count=-1)

    def test_single_field_rule_constructs(self) -> None:
        r = ActivitySignalRule(event_type="cae_created")
        assert r.event_type == "cae_created"
        assert r.min_count == 1

    def test_multi_field_rule_constructs(self) -> None:
        r = ActivitySignalRule(canonical_url_glob="/caes/*", type="submit", min_count=2)
        assert r.canonical_url_glob == "/caes/*"
        assert r.type == "submit"
        assert r.min_count == 2


# ---------------------------------------------------------------------------
# ActivitySignalRule.matches_action
# ---------------------------------------------------------------------------


class TestActivitySignalRuleMatching:
    def test_event_type_exact_match(self) -> None:
        r = ActivitySignalRule(event_type="cae_created")
        assert r.matches_action(_FakeAction(event_type="cae_created"))
        assert not r.matches_action(_FakeAction(event_type="cae_deleted"))
        # Falls back to ``type`` when ``event_type`` is absent — PostHog
        # wire format uses ``event``; the forwarder may project either.
        assert r.matches_action(_FakeAction(type="cae_created"))

    def test_canonical_url_glob_matches_id_pattern(self) -> None:
        r = ActivitySignalRule(canonical_url_glob="/caes/:id")
        assert r.matches_action(_FakeAction(canonical_url="/caes/:id"))
        # fnmatch glob "?" → exactly one char; not the typical case but
        # documents the underlying fnmatch semantics for config authors.
        assert not r.matches_action(_FakeAction(canonical_url="/caes"))

    def test_canonical_url_glob_supports_wildcards(self) -> None:
        r = ActivitySignalRule(canonical_url_glob="/caes/*")
        assert r.matches_action(_FakeAction(canonical_url="/caes/abc-123"))
        assert r.matches_action(_FakeAction(canonical_url="/caes/:id"))
        assert not r.matches_action(_FakeAction(canonical_url="/projects/abc"))

    def test_canonical_url_prefix(self) -> None:
        r = ActivitySignalRule(canonical_url_prefix="/caes/")
        assert r.matches_action(_FakeAction(canonical_url="/caes/abc"))
        assert r.matches_action(_FakeAction(canonical_url="/caes/abc/columns"))
        assert not r.matches_action(_FakeAction(canonical_url="/cae"))

    def test_title_contains_case_insensitive(self) -> None:
        r = ActivitySignalRule(title_contains="Create CAE")
        assert r.matches_action(_FakeAction(title="create cae"))
        assert r.matches_action(_FakeAction(title="The Create CAE button"))
        assert not r.matches_action(_FakeAction(title="Delete CAE"))

    def test_type_field_case_insensitive(self) -> None:
        r = ActivitySignalRule(type="submit")
        assert r.matches_action(_FakeAction(type="SUBMIT"))
        assert r.matches_action(_FakeAction(type="submit"))
        assert not r.matches_action(_FakeAction(type="click"))

    def test_multi_field_rule_requires_all_match(self) -> None:
        r = ActivitySignalRule(canonical_url_glob="/caes/*", type="submit")
        # Both fields satisfied
        assert r.matches_action(_FakeAction(canonical_url="/caes/new", type="submit"))
        # Only URL satisfies
        assert not r.matches_action(
            _FakeAction(canonical_url="/caes/new", type="click")
        )
        # Only type satisfies
        assert not r.matches_action(
            _FakeAction(canonical_url="/projects/new", type="submit")
        )

    def test_missing_field_does_not_crash(self) -> None:
        r = ActivitySignalRule(title_contains="Submit")
        # SimpleNamespace without a ``title`` attribute → missing → no match
        assert not r.matches_action(SimpleNamespace())
        # Dict without ``title`` key → no match
        assert not r.matches_action({})

    def test_dict_action_shape_works(self) -> None:
        r = ActivitySignalRule(canonical_url_glob="/caes/*")
        assert r.matches_action({"canonical_url": "/caes/abc"})
        assert not r.matches_action({"canonical_url": "/projects/abc"})

    def test_description_is_NOT_matchable(self) -> None:
        # PII safety: description carries user-typed content. No rule
        # field should be matchable against it. This test pins the
        # invariant — if a future change adds a ``description_contains``
        # rule, this test will fail and force the reviewer to think
        # about the PII implications.
        # The "trick" action has nothing in any other field, only
        # description. No rule should ever fire on it.
        action_only_desc = _FakeAction(description="user typed this private thing")
        for r in [
            ActivitySignalRule(event_type="user typed this private thing"),
            ActivitySignalRule(canonical_url_glob="*user typed*"),
            ActivitySignalRule(canonical_url_prefix="user"),
            ActivitySignalRule(title_contains="user typed"),
            ActivitySignalRule(type="user typed this private thing"),
        ]:
            assert not r.matches_action(action_only_desc), (
                f"rule {r.summary()} unexpectedly matched a description-only "
                "action; description must NEVER be matchable"
            )


# ---------------------------------------------------------------------------
# ActivitySignals parsing + validation
# ---------------------------------------------------------------------------


class TestActivitySignalsParsing:
    def test_round_trips_through_dict(self) -> None:
        original = ActivitySignals(
            any_of=(
                ActivitySignalRule(event_type="cae_created"),
                ActivitySignalRule(canonical_url_glob="/caes/*", min_count=2),
            ),
            completion_threshold=1,
        )
        d = original.to_dict()
        restored = ActivitySignals.from_dict(d)
        assert restored == original

    def test_returns_none_for_missing_or_empty(self) -> None:
        assert ActivitySignals.from_dict(None) is None
        assert ActivitySignals.from_dict({}) is None
        assert ActivitySignals.from_dict({"any_of": []}) is None
        assert ActivitySignals.from_dict({"any_of": "not a list"}) is None

    def test_drops_individual_bad_rules_keeps_good_ones(self) -> None:
        d = {
            "any_of": [
                {"event_type": "good_event"},
                {"min_count": 5},  # no matchable fields → rejected
                "not a dict",  # skipped
                {"title_contains": "Submit"},
            ]
        }
        signals = ActivitySignals.from_dict(d)
        assert signals is not None
        assert len(signals.any_of) == 2
        assert signals.any_of[0].event_type == "good_event"
        assert signals.any_of[1].title_contains == "Submit"

    def test_returns_none_when_all_rules_fail_to_parse(self) -> None:
        d = {"any_of": [{"min_count": 1}, "garbage"]}
        assert ActivitySignals.from_dict(d) is None

    def test_completion_threshold_defaults_to_one(self) -> None:
        signals = ActivitySignals.from_dict({"any_of": [{"event_type": "x"}]})
        assert signals is not None
        assert signals.completion_threshold == 1

    def test_rejects_empty_any_of_at_construction(self) -> None:
        with pytest.raises(ValueError, match="any_of must be non-empty"):
            ActivitySignals(any_of=())


# ---------------------------------------------------------------------------
# OnboardingWorkflow integration with activity_signals
# ---------------------------------------------------------------------------


class TestOnboardingWorkflowActivitySignals:
    def test_workflow_without_signals_round_trips(self) -> None:
        wf = OnboardingWorkflow(workflow_id="w1", name="W1")
        restored = OnboardingWorkflow.from_dict(wf.to_dict())
        assert restored == wf
        assert restored.activity_signals is None

    def test_workflow_with_signals_round_trips(self) -> None:
        wf = OnboardingWorkflow(
            workflow_id="w1",
            name="W1",
            activity_signals=ActivitySignals(
                any_of=(ActivitySignalRule(event_type="x"),),
            ),
        )
        restored = OnboardingWorkflow.from_dict(wf.to_dict())
        assert restored == wf

    def test_workflow_with_malformed_signals_degrades_gracefully(self) -> None:
        # A typo in the config shouldn't fail the whole product config
        # load — the workflow parses, just without signals (so it falls
        # back to tour + judge for completion detection).
        wf = OnboardingWorkflow.from_dict(
            {
                "workflow_id": "w1",
                "name": "W1",
                "activity_signals": {"any_of": [{"unknown_field": "x"}]},
            }
        )
        assert wf.workflow_id == "w1"
        assert wf.activity_signals is None


# ---------------------------------------------------------------------------
# detect_completed_workflows_from_activity
# ---------------------------------------------------------------------------


class TestDetectCompletedWorkflowsFromActivity:
    def test_returns_empty_when_no_workflows_have_signals(self) -> None:
        plan = OnboardingPlan(workflows=[_wf("w1"), _wf("w2")])
        result = detect_completed_workflows_from_activity(
            plan.workflows, [_FakeAction(event_type="cae_created")]
        )
        assert result == {}

    def test_returns_empty_when_no_actions(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(
                        any_of=(ActivitySignalRule(event_type="cae_created"),)
                    ),
                )
            ]
        )
        result = detect_completed_workflows_from_activity(plan.workflows, [])
        assert result == {}

    def test_single_rule_match_completes_workflow(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "flow-create-cae",
                    ActivitySignals(
                        any_of=(ActivitySignalRule(event_type="cae_created"),)
                    ),
                )
            ]
        )
        actions = [_FakeAction(event_type="cae_created")]
        result = detect_completed_workflows_from_activity(plan.workflows, actions)
        assert "flow-create-cae" in result
        match = result["flow-create-cae"]
        assert isinstance(match, ActivityMatch)
        assert match.workflow_id == "flow-create-cae"
        assert match.match_count == 1
        assert "event=cae_created" in match.rule_summary

    def test_or_semantics_first_matching_rule_wins(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(
                        any_of=(
                            ActivitySignalRule(event_type="primary_signal"),
                            ActivitySignalRule(canonical_url_glob="/fallback/*"),
                        )
                    ),
                )
            ]
        )
        # Primary doesn't match, fallback does
        result = detect_completed_workflows_from_activity(
            plan.workflows,
            [_FakeAction(canonical_url="/fallback/abc")],
        )
        assert "w1" in result
        assert result["w1"].matched_rule.canonical_url_glob == "/fallback/*"

    def test_min_count_threshold_requires_repeats(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(
                        any_of=(
                            ActivitySignalRule(
                                canonical_url_glob="/caes/*", min_count=3
                            ),
                        )
                    ),
                )
            ]
        )
        # Two matches < threshold → not fired
        assert (
            detect_completed_workflows_from_activity(
                plan.workflows,
                [
                    _FakeAction(canonical_url="/caes/a"),
                    _FakeAction(canonical_url="/caes/b"),
                ],
            )
            == {}
        )
        # Three matches ≥ threshold → fired
        result = detect_completed_workflows_from_activity(
            plan.workflows,
            [
                _FakeAction(canonical_url="/caes/a"),
                _FakeAction(canonical_url="/caes/b"),
                _FakeAction(canonical_url="/caes/c"),
            ],
        )
        assert "w1" in result
        assert result["w1"].match_count == 3

    def test_already_completed_workflow_is_skipped(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(any_of=(ActivitySignalRule(event_type="x"),)),
                ),
                _wf(
                    "w2",
                    ActivitySignals(any_of=(ActivitySignalRule(event_type="y"),)),
                ),
            ]
        )
        actions = [
            _FakeAction(event_type="x"),
            _FakeAction(event_type="y"),
        ]
        # w1 already done → only w2 surfaces (idempotency)
        result = detect_completed_workflows_from_activity(
            plan.workflows, actions, already_completed={"w1"}
        )
        assert set(result.keys()) == {"w2"}

    def test_multiple_workflows_complete_in_same_batch(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "create",
                    ActivitySignals(
                        any_of=(ActivitySignalRule(event_type="cae_created"),)
                    ),
                ),
                _wf(
                    "columns",
                    ActivitySignals(
                        any_of=(ActivitySignalRule(event_type="column_added"),)
                    ),
                ),
            ]
        )
        actions = [
            _FakeAction(event_type="cae_created"),
            _FakeAction(event_type="column_added"),
        ]
        result = detect_completed_workflows_from_activity(plan.workflows, actions)
        assert set(result.keys()) == {"create", "columns"}

    def test_workflows_without_signals_are_ignored(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "with_signals",
                    ActivitySignals(any_of=(ActivitySignalRule(event_type="x"),)),
                ),
                _wf("no_signals"),  # no activity_signals → never auto-completes
            ]
        )
        result = detect_completed_workflows_from_activity(
            plan.workflows, [_FakeAction(event_type="x")]
        )
        assert set(result.keys()) == {"with_signals"}

    def test_already_completed_is_normalised(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(any_of=(ActivitySignalRule(event_type="x"),)),
                )
            ]
        )
        # Whitespace + empty strings filtered out; should still skip "w1"
        result = detect_completed_workflows_from_activity(
            plan.workflows,
            [_FakeAction(event_type="x")],
            already_completed=["  w1  ", "", "   "],
        )
        assert result == {}

    def test_evidence_string_is_informative(self) -> None:
        plan = OnboardingPlan(
            workflows=[
                _wf(
                    "w1",
                    ActivitySignals(
                        any_of=(
                            ActivitySignalRule(
                                canonical_url_glob="/caes/*", min_count=2
                            ),
                        )
                    ),
                )
            ]
        )
        result = detect_completed_workflows_from_activity(
            plan.workflows,
            [
                _FakeAction(canonical_url="/caes/a"),
                _FakeAction(canonical_url="/caes/b"),
            ],
        )
        evidence = result["w1"].evidence_string
        assert "activity_signal" in evidence
        assert "url~/caes/*" in evidence
        assert "x2" in evidence  # match_count


# ---------------------------------------------------------------------------
# OnboardingPlan ⇄ detector integration (config parse path)
# ---------------------------------------------------------------------------


class TestOnboardingPlanWithActivitySignalsConfig:
    def test_plan_parses_activity_signals_from_real_config_shape(self) -> None:
        raw = [
            {
                "workflow_id": "flow-admin-create-product",
                "name": "Create your CAE",
                "role": "admin",
                "activity_signals": {
                    "any_of": [
                        {"event_type": "cae_created"},
                        {"canonical_url_glob": "/caes/:id"},
                    ]
                },
            }
        ]
        plan = OnboardingPlan.from_config(raw)
        wf = plan.workflows[0]
        assert wf.activity_signals is not None
        assert len(wf.activity_signals.any_of) == 2

        result = detect_completed_workflows_from_activity(
            plan.workflows, [_FakeAction(canonical_url="/caes/:id")]
        )
        assert "flow-admin-create-product" in result
