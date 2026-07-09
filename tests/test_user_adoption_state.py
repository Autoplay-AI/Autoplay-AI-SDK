"""Tests for the per-user adoption state model + helpers."""

from __future__ import annotations

import json

import pytest

from autoplay_sdk.user_adoption_state import (
    ExplorationGateConfig,
    JourneyState,
    MasteryLevel,
    OnboardingPlan,
    OnboardingWorkflow,
    StepProgress,
    UserAdoptionState,
    WorkflowProgress,
    WorkflowStatus,
    build_tour_match_input,
    evaluate_hard_gate,
    is_plan_complete,
    parse_tour_match_output,
    split_workflows,
    step_completion_ratio,
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class TestUserAdoptionState:
    def test_requires_user_id(self) -> None:
        with pytest.raises(ValueError):
            UserAdoptionState(user_id="")

    def test_defaults(self) -> None:
        s = UserAdoptionState(user_id="u1")
        assert s.journey_state == JourneyState.ONBOARDING
        assert s.mastery.level == MasteryLevel.NOVICE
        assert s.mastery.rating == 0
        assert s.role is None

    def test_role_is_dynamic_metadata(self) -> None:
        s = UserAdoptionState(user_id="u1", metadata={"role": "consultant", "x": 1})
        assert s.role == "consultant"
        # arbitrary keys survive
        assert s.metadata["x"] == 1

    def test_set_mastery_clamps_rating(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.set_mastery(rating=99, level=MasteryLevel.POWER_USER, description="r")
        assert s.mastery.rating == 10
        s.set_mastery(rating=-5, level=MasteryLevel.NOVICE)
        assert s.mastery.rating == 0

    def test_set_journey_state(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.set_journey_state(JourneyState.ONBOARDED, reason="done")
        assert s.journey_state == JourneyState.ONBOARDED

    def test_record_discovered_features_dedupes(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.record_discovered_features(["a", "b", "a", ""])
        assert s.discovered_features == ["a", "b"]

    def test_mark_welcomed(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.mark_welcomed(now=123.0)
        assert s.onboarding.welcomed is True
        assert s.onboarding.last_welcome_at == 123.0
        assert s.onboarding.proactive_support_count == 1

    def test_workflow_progress_upsert_and_helpers(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "flow-a",
            status=WorkflowStatus.COMPLETED,
            confidence=0.9,
            evidence="x",
            now=10.0,
        )
        s.onboarding.upsert_workflow_progress(
            "flow-b", status=WorkflowStatus.IN_PROGRESS, confidence=0.5, now=10.0
        )
        assert s.onboarding.completed_workflow_ids == ["flow-a"]
        assert s.onboarding.in_progress_workflow_ids == ["flow-b"]
        wp = s.onboarding.workflow_progress["flow-a"]
        assert wp.completed_at == 10.0
        assert s.onboarding.outstanding_workflow_ids(
            ["flow-a", "flow-b", "flow-c"]
        ) == [
            "flow-b",
            "flow-c",
        ]

    def test_confidence_clamped(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "flow-a", status=WorkflowStatus.IN_PROGRESS, confidence=5.0
        )
        assert s.onboarding.workflow_progress["flow-a"].confidence == 1.0

    def test_workflow_progress_source_round_trip(self) -> None:
        """``source`` is persisted in the snapshot so observability +
        per-channel prompt copy variation work after a reload."""
        from autoplay_sdk.user_adoption_state import (
            WORKFLOW_PROGRESS_SOURCE_ACTIVITY,
            WORKFLOW_PROGRESS_SOURCE_UNKNOWN,
        )

        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "flow-a",
            status=WorkflowStatus.COMPLETED,
            confidence=1.0,
            source=WORKFLOW_PROGRESS_SOURCE_ACTIVITY,
        )
        # Round-trip preserves source
        restored = UserAdoptionState.from_dict(json.loads(json.dumps(s.to_dict())))
        assert (
            restored.onboarding.workflow_progress["flow-a"].source
            == WORKFLOW_PROGRESS_SOURCE_ACTIVITY
        )
        # Legacy snapshot (pre-source field) → "unknown" default, never
        # silently relabelled as "tour"
        snap = UserAdoptionState(user_id="u2").to_dict()
        snap["onboarding"]["workflow_progress"] = {
            "flow-x": {
                "workflow_id": "flow-x",
                "status": WorkflowStatus.COMPLETED.value,
                "confidence": 1.0,
                # NOTE: no "source" key — legacy
            }
        }
        restored2 = UserAdoptionState.from_dict(snap)
        assert (
            restored2.onboarding.workflow_progress["flow-x"].source
            == WORKFLOW_PROGRESS_SOURCE_UNKNOWN
        )

    def test_upsert_preserves_source_when_not_specified(self) -> None:
        """The welcome-runner pre-pass re-stamps already-completed
        workflows defensively. Passing ``source=None`` must keep the
        existing authoritative source (e.g. 'tour') intact — otherwise
        the pre-pass would overwrite real provenance with whatever
        generic label the caller forgot to pass."""
        from autoplay_sdk.user_adoption_state import (
            WORKFLOW_PROGRESS_SOURCE_TOUR,
        )

        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "flow-a",
            status=WorkflowStatus.COMPLETED,
            confidence=1.0,
            source=WORKFLOW_PROGRESS_SOURCE_TOUR,
        )
        assert (
            s.onboarding.workflow_progress["flow-a"].source
            == WORKFLOW_PROGRESS_SOURCE_TOUR
        )
        # Re-upsert without source — preserves the original
        s.onboarding.upsert_workflow_progress(
            "flow-a",
            status=WorkflowStatus.COMPLETED,
            confidence=1.0,
        )
        assert (
            s.onboarding.workflow_progress["flow-a"].source
            == WORKFLOW_PROGRESS_SOURCE_TOUR
        )

    def test_roundtrip(self) -> None:
        s = UserAdoptionState(
            user_id="u1", metadata={"role": "consultant", "n": {"k": 1}}
        )
        s.set_mastery(rating=4, level=MasteryLevel.INTERMEDIATE, description="r")
        s.set_journey_state(JourneyState.ONBOARDED)
        s.record_discovered_features(["templates"])
        s.onboarding.upsert_workflow_progress(
            "flow-a", status=WorkflowStatus.COMPLETED, confidence=0.8, evidence="did"
        )
        restored = UserAdoptionState.from_dict(json.loads(json.dumps(s.to_dict())))
        assert restored.user_id == "u1"
        assert restored.role == "consultant"
        assert restored.metadata["n"] == {"k": 1}
        assert restored.journey_state == JourneyState.ONBOARDED
        assert restored.mastery.rating == 4
        assert restored.mastery.level == MasteryLevel.INTERMEDIATE
        assert restored.discovered_features == ["templates"]
        assert restored.onboarding.completed_workflow_ids == ["flow-a"]

    def test_from_dict_unknown_version_raises(self) -> None:
        with pytest.raises(ValueError):
            UserAdoptionState.from_dict({"_v": 999, "user_id": "u1"})

    def test_from_dict_coerces_unknown_enums(self) -> None:
        snap = UserAdoptionState(user_id="u1").to_dict()
        snap["journey_state"] = "bogus"
        snap["mastery"]["level"] = "bogus"
        snap["onboarding"]["workflow_progress"] = {
            "flow-a": {"workflow_id": "flow-a", "status": "bogus"}
        }
        restored = UserAdoptionState.from_dict(snap)
        assert restored.journey_state == JourneyState.ONBOARDING
        assert restored.mastery.level == MasteryLevel.NOVICE
        assert (
            restored.onboarding.workflow_progress["flow-a"].status
            == WorkflowStatus.NOT_STARTED
        )

    @pytest.mark.parametrize("bad_metadata", [None, [], "consultant", 42])
    def test_from_dict_non_dict_metadata_becomes_empty(self, bad_metadata) -> None:
        """Regression for cubic P2: a corrupt snapshot with non-dict
        metadata must not crash the ``role`` property the gate reads."""
        snap = UserAdoptionState(user_id="u1").to_dict()
        snap["metadata"] = bad_metadata
        restored = UserAdoptionState.from_dict(snap)
        assert restored.metadata == {}
        assert restored.role is None  # would have raised pre-fix

    @pytest.mark.parametrize(
        "non_finite_ts",
        [float("nan"), float("inf"), float("-inf")],
    )
    def test_from_dict_rejects_non_finite_timestamps(self, non_finite_ts) -> None:
        """Regression for cubic P2: NaN / +-Inf pass ``float()`` cleanly
        and would silently break cooldowns (every comparison against
        NaN is False, so a NaN ``last_judged_at`` makes the judge
        re-fire on every call). Reject them as invalid timestamps.
        """
        import math

        snap = UserAdoptionState(user_id="u1").to_dict()
        snap["onboarding"]["exploration_started_at"] = non_finite_ts
        snap["first_seen_at"] = non_finite_ts
        snap["last_updated_at"] = non_finite_ts
        snap["last_judged_at"] = non_finite_ts
        snap["onboarding"]["last_welcome_at"] = non_finite_ts
        snap["onboarding"]["last_reasoned_at"] = non_finite_ts
        restored = UserAdoptionState.from_dict(snap)
        # Required timestamps fall back to a real finite float.
        assert math.isfinite(restored.first_seen_at)
        assert math.isfinite(restored.last_updated_at)
        assert math.isfinite(restored.onboarding.exploration_started_at)
        # Optional timestamps fall back to None (gate / judge then
        # treats them as "never happened" — the correct default).
        assert restored.last_judged_at is None
        assert restored.onboarding.last_welcome_at is None
        assert restored.onboarding.last_reasoned_at is None

    @pytest.mark.parametrize("bad_ts", ["not a number", None, [1, 2], {"x": 1}])
    def test_from_dict_non_numeric_timestamps_coerced(self, bad_ts) -> None:
        """exploration_started_at / first_seen_at / etc. must coerce
        defensively — downstream arithmetic must not crash on a corrupt
        snapshot."""
        snap = UserAdoptionState(user_id="u1").to_dict()
        snap["onboarding"]["exploration_started_at"] = bad_ts
        snap["first_seen_at"] = bad_ts
        snap["last_updated_at"] = bad_ts
        snap["last_judged_at"] = bad_ts
        snap["onboarding"]["last_welcome_at"] = bad_ts
        restored = UserAdoptionState.from_dict(snap)
        # All non-optional timestamps fell back to a real float.
        assert isinstance(restored.first_seen_at, float)
        assert isinstance(restored.last_updated_at, float)
        assert isinstance(restored.onboarding.exploration_started_at, float)
        # Optional ones become None on parse failure.
        assert restored.last_judged_at is None
        assert restored.onboarding.last_welcome_at is None
        # Downstream arithmetic doesn't raise.
        _ = 1234.0 - restored.onboarding.exploration_started_at


# ---------------------------------------------------------------------------
# Exploration gate
# ---------------------------------------------------------------------------


class TestExplorationGate:
    def _state(self, role: str = "consultant") -> UserAdoptionState:
        return UserAdoptionState(user_id="u1", metadata={"role": role})

    def _cfg(self, **kw) -> ExplorationGateConfig:
        base = dict(
            role_allowlist=frozenset({"consultant"}),
            min_seconds_on_app=60.0,
            min_distinct_features=3,
            welcome_cooldown_s=600.0,
            max_proactive_support=3,
        )
        base.update(kw)
        return ExplorationGateConfig(**base)

    def test_passes_when_floor_met(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(),
        )
        assert ok is True and reason == "ok"

    def test_blocks_wrong_role(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(role="admin"),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(),
        )
        assert ok is False and reason.startswith("role_not_allowed")

    def test_role_match_is_case_insensitive(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(role="Consultant"),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(),
        )
        assert ok is True and reason == "ok"

    def test_allowlist_casing_is_normalized(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(role="consultant"),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(role_allowlist=frozenset({"Consultant"})),
        )
        assert ok is True and reason == "ok"

    def test_role_match_tolerates_casing_and_spacing(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(role="  Consultant "),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(),
        )
        assert ok is True and reason == "ok"

    def test_blocks_too_little_time(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(),
            now=1000.0,
            seconds_on_app=10,
            distinct_features_seen=5,
            cfg=self._cfg(),
        )
        assert ok is False and reason == "exploring_min_time_not_met"

    def test_blocks_too_few_features(self) -> None:
        ok, reason = evaluate_hard_gate(
            self._state(),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=1,
            cfg=self._cfg(),
        )
        assert ok is False and reason == "exploring_min_features_not_met"

    def test_blocks_within_cooldown(self) -> None:
        s = self._state()
        s.onboarding.last_welcome_at = 990.0
        ok, reason = evaluate_hard_gate(
            s, now=1000.0, seconds_on_app=120, distinct_features_seen=5, cfg=self._cfg()
        )
        assert ok is False and reason == "within_cooldown"

    def test_blocks_when_nudge_cap_reached(self) -> None:
        s = self._state()
        s.onboarding.proactive_support_count = 3
        ok, reason = evaluate_hard_gate(
            s, now=1000.0, seconds_on_app=120, distinct_features_seen=5, cfg=self._cfg()
        )
        assert ok is False and reason == "nudge_cap_reached"

    def test_blocks_when_already_onboarded(self) -> None:
        s = self._state()
        s.set_journey_state(JourneyState.ONBOARDED)
        ok, reason = evaluate_hard_gate(
            s, now=1000.0, seconds_on_app=120, distinct_features_seen=5, cfg=self._cfg()
        )
        assert ok is False and reason == "already_onboarded"

    @pytest.mark.parametrize(
        "snap_role,allowlist_role",
        [
            ("Consultant", "consultant"),
            ("CONSULTANT", "consultant"),
            ("consultant", "Consultant"),
            ("Consultant", "Consultant"),
        ],
    )
    def test_role_allowlist_is_case_insensitive(
        self, snap_role: str, allowlist_role: str
    ) -> None:
        """Regression for cubic P2: a "Consultant" snapshot or a
        ``frozenset({"Consultant"})`` allowlist must not produce
        accidental blocks just because of casing."""
        ok, reason = evaluate_hard_gate(
            self._state(role=snap_role),
            now=1000.0,
            seconds_on_app=120,
            distinct_features_seen=5,
            cfg=self._cfg(role_allowlist=frozenset({allowlist_role})),
        )
        assert ok is True, f"unexpected block: {reason}"


# ---------------------------------------------------------------------------
# Onboarding plan
# ---------------------------------------------------------------------------


class TestOnboardingPlan:
    def test_parse_and_role_filter(self) -> None:
        plan = OnboardingPlan.from_config(
            [
                {"workflow_id": "flow-a", "name": "A"},
                {"workflow_id": "flow-b", "name": "B", "role": "admin"},
                {"name": "missing id"},
            ]
        )
        assert plan.workflow_ids == ["flow-a", "flow-b"]
        assert plan.for_role("consultant").workflow_ids == ["flow-a"]
        assert plan.for_role("admin").workflow_ids == ["flow-a", "flow-b"]

    def test_workflow_with_null_name_does_not_become_string_None(self) -> None:
        """Regression for cubic P3: ``str(None)`` returns the literal
        "None" — should be empty so it renders cleanly in the chat UI."""
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "name": None,
                    "description": None,
                    "why": None,
                }
            ]
        )
        assert plan.workflows[0].name == ""
        assert plan.workflows[0].description == ""
        # Same fallback for the `why` field added in v0.2 of the
        # onboarding plan schema — null in config must not surface as
        # the literal string "None" in the prompt input.
        assert plan.workflows[0].why == ""

    def test_workflow_why_field_roundtrips(self) -> None:
        """`why` is the user-facing "why this matters" copy lifted onto
        each SuggestedFlow card. Must round-trip through from_dict /
        to_dict cleanly, AND be omitted from to_dict when empty so old
        consumers reading the JSON don't see a blank key."""
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "name": "A",
                    "description": "what it does",
                    "why": "why it matters to the user",
                },
                {
                    "workflow_id": "flow-b",
                    "name": "B",
                    # no `why` — older config without the v0.2 field
                },
            ]
        )
        a, b = plan.workflows
        assert a.why == "why it matters to the user"
        assert b.why == ""

        a_dict = a.to_dict()
        b_dict = b.to_dict()
        assert a_dict["why"] == "why it matters to the user"
        # Empty `why` must NOT serialise — keeps the LLM's prompt input
        # tight (no `"why": ""` lines polluting required_workflows_json).
        assert "why" not in b_dict

    def test_from_dict_normalizes_null_metadata(self) -> None:
        wf = OnboardingWorkflow.from_dict(
            {"workflow_id": "flow-a", "name": None, "description": None}
        )
        assert wf.name == ""
        assert wf.description == ""
        assert wf.role is None

    def test_from_dict_blank_role_means_all_roles(self) -> None:
        plan = OnboardingPlan.from_config(
            [
                {"workflow_id": "flow-a", "role": ""},
                {"workflow_id": "flow-b", "role": "   "},
            ]
        )
        assert all(w.role is None for w in plan.workflows)
        assert plan.for_role("consultant").workflow_ids == ["flow-a", "flow-b"]
        assert plan.for_role("admin").workflow_ids == ["flow-a", "flow-b"]

    def test_split_workflows(self) -> None:
        plan = OnboardingPlan.from_config(
            [{"workflow_id": "a"}, {"workflow_id": "b"}, {"workflow_id": "c"}]
        )
        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "a", status=WorkflowStatus.COMPLETED, confidence=1.0
        )
        s.onboarding.upsert_workflow_progress(
            "b", status=WorkflowStatus.IN_PROGRESS, confidence=0.5
        )
        completed, in_progress, outstanding = split_workflows(
            plan, s.onboarding.workflow_progress
        )
        assert completed == ["a"]
        assert in_progress == ["b"]
        assert outstanding == ["b", "c"]

    def test_parse_steps_from_config(self) -> None:
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "name": "A",
                    "steps": [
                        {"step_id": "s1", "name": "Step 1", "description": "do x"},
                        {"step_id": "s2", "name": "Step 2", "required": False},
                    ],
                }
            ]
        )
        wf = plan.workflows[0]
        assert [s.step_id for s in wf.steps] == ["s1", "s2"]
        assert wf.steps[0].required is True
        assert wf.steps[0].description == "do x"
        assert wf.steps[1].required is False
        # Only the "required" steps surface in the helper, in declared order.
        assert wf.required_step_ids == ["s1"]

    def test_steps_roundtrip_and_omitted_when_empty(self) -> None:
        wf = OnboardingWorkflow.from_dict(
            {
                "workflow_id": "flow-a",
                "name": "A",
                "steps": [
                    {"step_id": "s1", "name": "Step 1", "description": "do x"},
                    {"step_id": "s2", "name": "Step 2", "required": False},
                ],
            }
        )
        d = wf.to_dict()
        # Round-trips cleanly back into equal WorkflowStep objects.
        restored = OnboardingWorkflow.from_dict(d)
        assert restored.steps == wf.steps
        # `required` only serialises when it diverges from the default True.
        assert "required" not in d["steps"][0]
        assert d["steps"][1]["required"] is False
        # A workflow with no steps must not emit a "steps" key, so older
        # consumers reading the JSON don't see a new empty field.
        bare = OnboardingWorkflow.from_dict({"workflow_id": "flow-b"})
        assert "steps" not in bare.to_dict()

    def test_parse_steps_skips_malformed_entries(self) -> None:
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "steps": [
                        {"step_id": "s1"},
                        {"name": "missing id"},
                        "not a dict",
                        {"step_id": "s2"},
                    ],
                }
            ]
        )
        assert [s.step_id for s in plan.workflows[0].steps] == ["s1", "s2"]

    def test_step_null_name_does_not_become_string_none(self) -> None:
        wf = OnboardingWorkflow.from_dict(
            {
                "workflow_id": "flow-a",
                "steps": [{"step_id": "s1", "name": None, "description": None}],
            }
        )
        assert wf.steps[0].name == ""
        assert wf.steps[0].description == ""


# ---------------------------------------------------------------------------
# Workflow steps: progress, completion, and display ratio
# ---------------------------------------------------------------------------


class TestWorkflowSteps:
    def test_upsert_step_progress_and_completed_ids(self) -> None:
        wp = WorkflowProgress(workflow_id="flow-a")
        wp.upsert_step_progress(
            "s1",
            status=WorkflowStatus.COMPLETED,
            confidence=0.9,
            evidence="x",
            now=10.0,
        )
        wp.upsert_step_progress(
            "s2", status=WorkflowStatus.IN_PROGRESS, confidence=0.4, now=10.0
        )
        assert wp.completed_step_ids == ["s1"]
        assert wp.steps["s1"].completed_at == 10.0
        assert wp.steps["s2"].completed_at is None

    def test_upsert_step_progress_completed_at_is_write_once(self) -> None:
        wp = WorkflowProgress(workflow_id="flow-a")
        wp.upsert_step_progress(
            "s1", status=WorkflowStatus.COMPLETED, confidence=0.9, now=10.0
        )
        # Re-completing later must NOT move the original completion stamp.
        wp.upsert_step_progress(
            "s1", status=WorkflowStatus.COMPLETED, confidence=1.0, now=99.0
        )
        assert wp.steps["s1"].completed_at == 10.0
        assert wp.steps["s1"].last_evaluated_at == 99.0

    def test_step_confidence_clamped(self) -> None:
        wp = WorkflowProgress(workflow_id="flow-a")
        wp.upsert_step_progress("s1", status=WorkflowStatus.IN_PROGRESS, confidence=5.0)
        assert wp.steps["s1"].confidence == 1.0

    def test_workflow_progress_roundtrips_nested_steps(self) -> None:
        wp = WorkflowProgress(workflow_id="flow-a", status=WorkflowStatus.COMPLETED)
        wp.upsert_step_progress(
            "s1",
            status=WorkflowStatus.COMPLETED,
            confidence=0.8,
            evidence="did",
            now=5.0,
        )
        restored = WorkflowProgress.from_dict(json.loads(json.dumps(wp.to_dict())))
        assert restored.workflow_id == "flow-a"
        assert restored.status == WorkflowStatus.COMPLETED
        assert restored.steps["s1"] == StepProgress(
            step_id="s1",
            status=WorkflowStatus.COMPLETED,
            confidence=0.8,
            evidence="did",
            completed_at=5.0,
            last_evaluated_at=5.0,
        )

    def test_step_progress_coerces_unknown_status(self) -> None:
        sp = StepProgress.from_dict({"step_id": "s1", "status": "bogus"})
        assert sp.status == WorkflowStatus.NOT_STARTED

    def test_steps_do_not_gate_workflow_completion(self) -> None:
        """A workflow is COMPLETED per the LLM even if its steps are not all
        individually done (variant-path case) — split_workflows still keys
        off WorkflowProgress.status, not the steps."""
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "steps": [{"step_id": "s1"}, {"step_id": "s2"}],
                }
            ]
        )
        wp = WorkflowProgress(workflow_id="flow-a", status=WorkflowStatus.COMPLETED)
        # No step progress recorded at all, yet the workflow is complete.
        completed, _in_progress, outstanding = split_workflows(plan, {"flow-a": wp})
        assert completed == ["flow-a"]
        assert outstanding == []
        assert is_plan_complete(plan, {"flow-a": wp}) is True

    def test_all_steps_done_but_workflow_not_completed_is_not_complete(self) -> None:
        """The inverse: every step COMPLETED but the LLM has not marked the
        workflow COMPLETED -> not complete (status is authoritative)."""
        plan = OnboardingPlan.from_config(
            [{"workflow_id": "flow-a", "steps": [{"step_id": "s1"}]}]
        )
        wp = WorkflowProgress(workflow_id="flow-a", status=WorkflowStatus.IN_PROGRESS)
        wp.upsert_step_progress("s1", status=WorkflowStatus.COMPLETED, confidence=1.0)
        assert is_plan_complete(plan, {"flow-a": wp}) is False

    def test_is_plan_complete_empty_plan_is_false(self) -> None:
        assert is_plan_complete(OnboardingPlan.from_config([]), {}) is False

    def test_step_completion_ratio(self) -> None:
        wf = OnboardingWorkflow.from_dict(
            {
                "workflow_id": "flow-a",
                "steps": [{"step_id": "s1"}, {"step_id": "s2"}, {"step_id": "s3"}],
            }
        )
        wp = WorkflowProgress(workflow_id="flow-a")
        wp.upsert_step_progress("s1", status=WorkflowStatus.COMPLETED, confidence=1.0)
        wp.upsert_step_progress("s2", status=WorkflowStatus.IN_PROGRESS, confidence=0.5)
        assert step_completion_ratio(wf, wp) == pytest.approx(1 / 3)
        # No declared steps -> neutral 0.0 (no special-casing for callers).
        bare = OnboardingWorkflow.from_dict({"workflow_id": "flow-b"})
        assert step_completion_ratio(bare, wp) == 0.0
        # No progress object yet -> 0.0.
        assert step_completion_ratio(wf, None) == 0.0

    def test_backward_compat_snapshot_without_steps(self) -> None:
        """An old snapshot (no per-workflow `steps` key) loads cleanly with an
        empty step dict and the same `_v`."""
        s = UserAdoptionState(user_id="u1")
        s.onboarding.upsert_workflow_progress(
            "flow-a", status=WorkflowStatus.IN_PROGRESS, confidence=0.5
        )
        snap = s.to_dict()
        # Simulate a pre-steps snapshot: strip the steps key the new code adds.
        snap["onboarding"]["workflow_progress"]["flow-a"].pop("steps", None)
        restored = UserAdoptionState.from_dict(json.loads(json.dumps(snap)))
        assert restored._v == s._v
        assert restored.onboarding.workflow_progress["flow-a"].steps == {}


# ---------------------------------------------------------------------------
# Onboarding plan: prerequisite chain + next-eligible
# ---------------------------------------------------------------------------


class TestOnboardingPlanPrerequisites:
    def test_prerequisite_workflow_ids_roundtrips(self) -> None:
        """`prerequisite_workflow_ids` is the v0.6 field that encodes the
        plan's dependency chain. Must accept a list of strings from
        config, expose them as a tuple in-memory (frozen dataclass
        constraint), and round-trip back to a JSON-friendly list. Empty
        / missing prereqs must NOT serialise into to_dict so the LLM
        prompt input stays tight when the workflow has no dependencies.
        """
        plan = OnboardingPlan.from_config(
            [
                {
                    "workflow_id": "flow-a",
                    "name": "A",
                    "prerequisite_workflow_ids": [],
                },
                {
                    "workflow_id": "flow-b",
                    "name": "B",
                    "prerequisite_workflow_ids": ["flow-a"],
                },
                {
                    "workflow_id": "flow-c",
                    "name": "C",
                    "prerequisite_workflow_ids": ["flow-a", "flow-b"],
                },
            ]
        )
        a, b, c = plan.workflows
        assert a.prerequisite_workflow_ids == ()
        assert b.prerequisite_workflow_ids == ("flow-a",)
        assert c.prerequisite_workflow_ids == ("flow-a", "flow-b")
        # Empty / missing prereqs are omitted from to_dict; non-empty
        # prereqs serialise back as a list (not a tuple).
        assert "prerequisite_workflow_ids" not in a.to_dict()
        assert b.to_dict()["prerequisite_workflow_ids"] == ["flow-a"]
        assert c.to_dict()["prerequisite_workflow_ids"] == ["flow-a", "flow-b"]

    def test_next_eligible_workflows_respects_prereq_chain(self) -> None:
        """Linear-chain golden path: A → B → C with C depending on
        both A and B. The eligible set must collapse to exactly the
        single next step at each stage, which is what gives the
        welcome / follow-up runners their "suggest only the next
        unlocked workflow" behaviour the operator asked for.
        """
        plan = OnboardingPlan.from_config(
            [
                {"workflow_id": "A"},
                {"workflow_id": "B", "prerequisite_workflow_ids": ["A"]},
                {"workflow_id": "C", "prerequisite_workflow_ids": ["A", "B"]},
            ]
        )

        # Nothing completed → only A is eligible (B blocked by A,
        # C blocked by A + B).
        assert [w.workflow_id for w in plan.next_eligible_workflows([])] == ["A"]
        # A done → B unlocks, C still blocked by B.
        assert [w.workflow_id for w in plan.next_eligible_workflows(["A"])] == ["B"]
        # A + B done → C unlocks.
        assert [w.workflow_id for w in plan.next_eligible_workflows(["A", "B"])] == [
            "C"
        ]
        # All done → empty (no eligible work remaining).
        assert plan.next_eligible_workflows(["A", "B", "C"]) == []

    def test_next_eligible_workflows_handles_parallel_branches(self) -> None:
        """When several workflows share the same prereqs (the admin plan
        shape: templates / views / dashboards all depend on
        create-product + columns) they all become simultaneously
        eligible. Declared order = priority — callers that want "the
        single next step" can just take [0].
        """
        plan = OnboardingPlan.from_config(
            [
                {"workflow_id": "create"},
                {
                    "workflow_id": "columns",
                    "prerequisite_workflow_ids": ["create"],
                },
                {
                    "workflow_id": "templates",
                    "prerequisite_workflow_ids": ["create", "columns"],
                },
                {
                    "workflow_id": "views",
                    "prerequisite_workflow_ids": ["create", "columns"],
                },
                {
                    "workflow_id": "dashboards",
                    "prerequisite_workflow_ids": ["create", "columns"],
                },
            ]
        )

        # After the create+columns spine, all three derived workflows
        # are eligible simultaneously — in declared order.
        eligible = [
            w.workflow_id for w in plan.next_eligible_workflows(["create", "columns"])
        ]
        assert eligible == ["templates", "views", "dashboards"]

    def test_next_eligible_workflows_dangling_prereq_does_not_deadlock(
        self, caplog
    ) -> None:
        """A typo in prereqs points at a workflow id that doesn't exist
        in the plan. That workflow becomes permanently ineligible
        (correct — its declared dependency is genuinely unmet) but
        crucially does NOT deadlock the rest of the plan. A WARNING
        log lets the operator spot the typo.
        """
        import logging

        plan = OnboardingPlan.from_config(
            [
                {"workflow_id": "A"},
                # Typo: prereq points at a workflow that doesn't exist.
                {"workflow_id": "B", "prerequisite_workflow_ids": ["typo"]},
                {"workflow_id": "C"},
            ]
        )
        with caplog.at_level(logging.WARNING):
            eligible_ids = [w.workflow_id for w in plan.next_eligible_workflows([])]
        # A and C are eligible (no prereqs); B is dropped (unmet prereq
        # "typo" can never be satisfied because it isn't in the plan).
        assert eligible_ids == ["A", "C"]
        # Warning surfaces the typo so the operator can fix the config.
        assert any(
            "unknown prerequisite" in rec.message and "typo" in rec.message
            for rec in caplog.records
        )

    def test_next_eligible_filters_completed_even_with_no_prereqs(self) -> None:
        """A completed workflow is never eligible, even if its prereqs
        are trivially satisfied. Guards against the runner suggesting
        a tour the user already finished.
        """
        plan = OnboardingPlan.from_config(
            [{"workflow_id": "A"}, {"workflow_id": "B"}, {"workflow_id": "C"}]
        )
        eligible_ids = [w.workflow_id for w in plan.next_eligible_workflows(["B"])]
        assert eligible_ids == ["A", "C"]


# ---------------------------------------------------------------------------
# Tour matching
# ---------------------------------------------------------------------------


class TestTourMatching:
    _catalog = [
        {"tour_id": "flow-a", "name": "A", "use_when": "create", "role": "consultant"},
        {"tour_id": "flow-b", "name": "B", "use_when": "admin stuff", "role": "admin"},
        {"tour_id": "flow-c", "name": "C", "use_when": "anyone"},
    ]

    def test_build_input_filters_by_role(self) -> None:
        inp = build_tour_match_input(
            user_query="how do I create a project",
            role="consultant",
            tour_catalog=self._catalog,
        )
        assert set(inp["allowed_tour_ids"]) == {"flow-a", "flow-c"}
        assert "flow-b" not in inp["tour_catalog_text"]

    def test_parse_validates_and_drops_disallowed(self) -> None:
        raw = json.dumps(
            {
                "primary_tour_id": "flow-a",
                "related_tour_ids": ["flow-b", "flow-c", "flow-a", "bogus"],
                "reasoning": "x",
            }
        )
        res = parse_tour_match_output(
            raw, tour_catalog=self._catalog, role="consultant"
        )
        assert res.primary_tour_id == "flow-a"
        # flow-b is admin-only (dropped), flow-a is the primary (dropped), bogus invalid
        assert res.related_tour_ids == ["flow-c"]

    def test_parse_primary_not_in_catalog_becomes_none(self) -> None:
        raw = json.dumps({"primary_tour_id": "flow-b", "related_tour_ids": []})
        res = parse_tour_match_output(
            raw, tour_catalog=self._catalog, role="consultant"
        )
        assert res.primary_tour_id is None

    def test_parse_malformed_returns_empty(self) -> None:
        res = parse_tour_match_output(
            "not json", tour_catalog=self._catalog, role="consultant"
        )
        assert res.primary_tour_id is None
        assert res.related_tour_ids == []
        assert res.reasoning == "parse_error"

    @pytest.mark.parametrize(
        "non_list",
        [42, "flow-a", {"foo": "bar"}, True],
    )
    def test_parse_related_tour_ids_non_list_treated_as_missing(self, non_list) -> None:
        """Regression for cubic P2: misbehaving LLM may ship an integer /
        string / dict for ``related_tour_ids``; iterating those would
        raise or silently iterate characters and corrupt the result.
        """
        raw = json.dumps({"primary_tour_id": "flow-a", "related_tour_ids": non_list})
        res = parse_tour_match_output(
            raw, tour_catalog=self._catalog, role="consultant"
        )
        # Primary still picked up — only related is gracefully empty.
        assert res.primary_tour_id == "flow-a"
        assert res.related_tour_ids == []
