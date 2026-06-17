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
    UserAdoptionState,
    WorkflowStatus,
    build_tour_match_input,
    evaluate_hard_gate,
    parse_tour_match_output,
    split_workflows,
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
