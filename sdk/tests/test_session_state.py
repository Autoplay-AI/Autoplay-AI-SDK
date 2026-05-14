"""Tests for autoplay_sdk.agent_state_v2.SessionState (v3 spec).

Covers:
- ThinkingState cooldown tick / clear / active_cooldown_period_s
- SessionState interaction timeout expiry (PROACTIVE → THINKING, REACTIVE → THINKING)
- Transition rules and InvalidTransitionError
- Cooldown cleared by transition_to_reactive
- Visual guidance on SessionState (not per-state)
- set_visual_guidance raises from THINKING
- tick(tour_registry=...) per-tour timeout resolution
- record_tour_step on all three states
- Round-trip persistence (to_dict / from_dict)
"""

from __future__ import annotations

import time

import pytest

from autoplay_sdk.agent_state_v2 import (
    AgentStateV2,
    InvalidTransitionError,
    SessionState,
    ThinkingState,
)
from autoplay_sdk.proactive_triggers.tour_registry import TourDefinition, TourRegistry


# ---------------------------------------------------------------------------
# ThinkingState — cooldown
# ---------------------------------------------------------------------------


class TestThinkingStateCooldown:
    def test_can_go_proactive_when_no_cooldown(self) -> None:
        ts = ThinkingState()
        assert ts.can_go_proactive is True

    def test_can_go_proactive_blocked_when_cooldown_active(self) -> None:
        ts = ThinkingState()
        ts.start_cooldown()
        assert ts.can_go_proactive is False

    def test_tick_before_period_elapses_keeps_cooldown_active(self) -> None:
        ts = ThinkingState()
        ts.start_cooldown()
        ts.tick(cooldown_period_s=9999.0)
        assert ts.cooldown_active is True

    def test_tick_after_period_elapses_clears_cooldown(self) -> None:
        ts = ThinkingState(
            cooldown_active=True, cooldown_started_at=time.monotonic() - 100.0
        )
        ts.tick(cooldown_period_s=1.0)
        assert ts.cooldown_active is False
        assert ts.can_go_proactive is True

    def test_clear_cooldown_resets_all_fields(self) -> None:
        ts = ThinkingState()
        ts.start_cooldown(override_period_s=30.0)
        ts.clear_cooldown()
        assert ts.cooldown_active is False
        assert ts.cooldown_started_at == 0.0
        assert ts.active_cooldown_period_s is None

    def test_tick_no_op_when_no_cooldown(self) -> None:
        ts = ThinkingState()
        ts.tick(cooldown_period_s=1.0)
        assert ts.cooldown_active is False

    def test_start_cooldown_stores_override(self) -> None:
        ts = ThinkingState()
        ts.start_cooldown(override_period_s=120.0)
        assert ts.cooldown_active is True
        assert ts.active_cooldown_period_s == 120.0

    def test_tick_uses_override_period_over_session_default(self) -> None:
        # Override = 1 s (will expire), session default = 9999 s (wouldn't expire)
        ts = ThinkingState(
            cooldown_active=True,
            cooldown_started_at=time.monotonic() - 10.0,
            active_cooldown_period_s=1.0,
        )
        ts.tick(cooldown_period_s=9999.0)
        assert ts.cooldown_active is False

    def test_tick_respects_longer_override(self) -> None:
        # Override = 9999 s (won't expire), session default = 1 s (would expire)
        ts = ThinkingState(
            cooldown_active=True,
            cooldown_started_at=time.monotonic() - 10.0,
            active_cooldown_period_s=9999.0,
        )
        ts.tick(cooldown_period_s=1.0)
        assert ts.cooldown_active is True

    def test_round_trip_with_override(self) -> None:
        ts = ThinkingState()
        ts.start_cooldown(override_period_s=45.0)
        restored = ThinkingState.from_dict(ts.to_dict())
        assert restored.cooldown_active is True
        assert restored.active_cooldown_period_s == 45.0


# ---------------------------------------------------------------------------
# SessionState — interaction timeout
# ---------------------------------------------------------------------------


class TestSessionStateInteractionTimeout:
    def _session_in_proactive(self, timeout_s: float = 20.0) -> SessionState:
        s = SessionState(interaction_timeout_s=timeout_s)
        assert s.transition_to_proactive("trig_1") is True
        return s

    def _session_in_reactive(self, timeout_s: float = 20.0) -> SessionState:
        s = SessionState(interaction_timeout_s=timeout_s)
        s.transition_to_reactive()
        return s

    def test_proactive_no_timeout_stays_proactive(self) -> None:
        s = self._session_in_proactive(timeout_s=9999.0)
        s.tick()
        assert s.current_state == AgentStateV2.PROACTIVE

    def test_proactive_timeout_moves_to_thinking_with_cooldown(self) -> None:
        s = self._session_in_proactive(timeout_s=0.001)
        s.last_interaction_at = time.monotonic() - 10.0
        s.tick()
        assert s.current_state == AgentStateV2.THINKING
        assert s.thinking.cooldown_active is True

    def test_reactive_no_timeout_stays_reactive(self) -> None:
        s = self._session_in_reactive(timeout_s=9999.0)
        s.tick()
        assert s.current_state == AgentStateV2.REACTIVE

    def test_reactive_timeout_moves_to_thinking_with_cooldown(self) -> None:
        s = self._session_in_reactive(timeout_s=0.001)
        s.last_interaction_at = time.monotonic() - 10.0
        s.tick()
        assert s.current_state == AgentStateV2.THINKING
        assert s.thinking.cooldown_active is True

    def test_record_any_interaction_resets_timer_prevents_timeout(self) -> None:
        s = self._session_in_proactive(timeout_s=0.001)
        s.last_interaction_at = time.monotonic() - 10.0
        s.record_any_interaction()
        s.tick()
        assert s.current_state == AgentStateV2.PROACTIVE

    def test_cooldown_auto_clears_after_cooldown_period(self) -> None:
        s = SessionState(cooldown_period_s=1.0)
        s.thinking.start_cooldown()
        s.thinking.cooldown_started_at = time.monotonic() - 100.0
        s.tick()
        assert s.thinking.cooldown_active is False
        assert s.thinking.can_go_proactive is True

    def test_timeout_clears_visual_guidance_and_tour_id(self) -> None:
        s = self._session_in_proactive(timeout_s=0.001)
        s.visual_guidance_active = True
        s.active_tour_id = "tour_abc"
        s.last_interaction_at = time.monotonic() - 10.0
        s.tick()
        assert s.current_state == AgentStateV2.THINKING
        assert s.visual_guidance_active is False
        assert s.active_tour_id is None


# ---------------------------------------------------------------------------
# SessionState — tick with tour_registry per-tour timeout
# ---------------------------------------------------------------------------


class TestSessionStateTickWithTourRegistry:
    def _make_registry(
        self,
        user_tour_id: str,
        interaction_timeout_s: float,
        cooldown_period_s: float,
    ) -> TourRegistry:
        """Build a registry keyed by ``user_tour_id`` (provider flow ID).

        ``active_tour_id`` on :class:`SessionState` stores the provider flow ID,
        so the lookup uses ``get_by_user_tour_id()`` rather than ``get()``.
        """
        tour = TourDefinition(
            id="chip_" + user_tour_id,
            user_tour_id=user_tour_id,
            interaction_timeout_s=interaction_timeout_s,
            cooldown_period_s=cooldown_period_s,
        )
        return TourRegistry(product_id="p1", tours=[tour])

    def test_per_tour_timeout_used_when_active_tour_matches(self) -> None:
        # Session timeout = 9999 s (would never expire), tour timeout = 1 s (will expire).
        # active_tour_id holds the provider flow ID (user_tour_id).
        s = SessionState(interaction_timeout_s=9999.0)
        s.transition_to_proactive("trig_1")
        s.active_tour_id = "flow_abc"  # provider flow ID
        s.last_interaction_at = time.monotonic() - 10.0

        registry = self._make_registry(
            "flow_abc", interaction_timeout_s=1.0, cooldown_period_s=30.0
        )
        s.tick(tour_registry=registry)

        assert s.current_state == AgentStateV2.THINKING
        assert s.thinking.cooldown_active is True
        # The tour-specific cooldown_period_s should have been applied
        assert s.thinking.active_cooldown_period_s == 30.0

    def test_session_default_timeout_used_when_tour_not_in_registry(self) -> None:
        # Session timeout = 1 s (will expire), tour timeout = 9999 s (wouldn't).
        # active_tour_id doesn't match any user_tour_id in registry → session default used.
        s = SessionState(interaction_timeout_s=1.0)
        s.transition_to_proactive("trig_1")
        s.active_tour_id = "unknown_flow"
        s.last_interaction_at = time.monotonic() - 10.0

        registry = self._make_registry(
            "other_flow", interaction_timeout_s=9999.0, cooldown_period_s=120.0
        )
        s.tick(tour_registry=registry)

        # Falls back to session default (1 s), so it should have timed out
        assert s.current_state == AgentStateV2.THINKING

    def test_session_default_used_when_no_active_tour(self) -> None:
        # Session timeout = 1 s; no active tour even though registry is present
        s = SessionState(interaction_timeout_s=1.0)
        s.transition_to_proactive("trig_1")
        s.last_interaction_at = time.monotonic() - 10.0
        assert s.active_tour_id is None

        registry = self._make_registry(
            "some_flow", interaction_timeout_s=9999.0, cooldown_period_s=120.0
        )
        s.tick(tour_registry=registry)

        assert s.current_state == AgentStateV2.THINKING

    def test_session_default_used_when_registry_is_none(self) -> None:
        s = SessionState(interaction_timeout_s=1.0)
        s.transition_to_proactive("trig_1")
        s.active_tour_id = "some_flow"
        s.last_interaction_at = time.monotonic() - 10.0
        s.tick(tour_registry=None)
        assert s.current_state == AgentStateV2.THINKING


# ---------------------------------------------------------------------------
# SessionState — transition rules and InvalidTransitionError
# ---------------------------------------------------------------------------


class TestSessionStateTransitions:
    def test_transition_to_proactive_from_thinking_no_cooldown_succeeds(self) -> None:
        s = SessionState()
        result = s.transition_to_proactive("trig_1")
        assert result is True
        assert s.current_state == AgentStateV2.PROACTIVE

    def test_transition_to_proactive_blocked_by_cooldown(self) -> None:
        s = SessionState()
        s.thinking.start_cooldown()
        result = s.transition_to_proactive("trig_1")
        assert result is False
        assert s.current_state == AgentStateV2.THINKING

    def test_transition_to_proactive_from_proactive_raises(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        with pytest.raises(InvalidTransitionError):
            s.transition_to_proactive("trig_2")

    def test_transition_to_proactive_from_reactive_raises(self) -> None:
        s = SessionState()
        s.transition_to_reactive()
        with pytest.raises(InvalidTransitionError):
            s.transition_to_proactive("trig_1")

    def test_transition_to_reactive_from_thinking_succeeds(self) -> None:
        s = SessionState()
        s.transition_to_reactive()
        assert s.current_state == AgentStateV2.REACTIVE

    def test_transition_to_reactive_clears_cooldown(self) -> None:
        s = SessionState()
        s.thinking.start_cooldown()
        assert s.thinking.cooldown_active is True
        s.transition_to_reactive()
        assert s.thinking.cooldown_active is False

    def test_transition_to_reactive_from_proactive_raises(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        with pytest.raises(InvalidTransitionError):
            s.transition_to_reactive()

    def test_transition_to_reactive_from_reactive_raises(self) -> None:
        s = SessionState()
        s.transition_to_reactive()
        with pytest.raises(InvalidTransitionError):
            s.transition_to_reactive()


# ---------------------------------------------------------------------------
# SessionState — full round-trip: timeout → cooldown → proactive again
# ---------------------------------------------------------------------------


class TestSessionStateTimeoutRoundTrip:
    def test_full_round_trip(self) -> None:
        s = SessionState(interaction_timeout_s=0.001, cooldown_period_s=1.0)
        assert s.transition_to_proactive("trig_1") is True
        assert s.current_state == AgentStateV2.PROACTIVE

        s.last_interaction_at = time.monotonic() - 10.0
        s.tick()
        assert s.current_state == AgentStateV2.THINKING
        assert s.thinking.cooldown_active is True

        assert s.transition_to_proactive("trig_2") is False

        s.thinking.cooldown_started_at = time.monotonic() - 100.0
        s.tick()
        assert s.thinking.cooldown_active is False

        assert s.transition_to_proactive("trig_3") is True


# ---------------------------------------------------------------------------
# SessionState — visual guidance (session-level)
# ---------------------------------------------------------------------------


class TestSessionStateVisualGuidance:
    def test_set_visual_guidance_true_in_proactive(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        before = s.last_interaction_at
        s.set_visual_guidance(True, tour_id="tour_1")
        assert s.visual_guidance_active is True
        assert s.active_tour_id == "tour_1"
        assert s.last_interaction_at >= before

    def test_set_visual_guidance_true_in_reactive(self) -> None:
        s = SessionState()
        s.transition_to_reactive()
        s.set_visual_guidance(True, tour_id="tour_2")
        assert s.visual_guidance_active is True
        assert s.active_tour_id == "tour_2"

    def test_set_visual_guidance_false_clears_both_fields(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        s.set_visual_guidance(True, tour_id="tour_1")
        s.set_visual_guidance(False)
        assert s.visual_guidance_active is False
        assert s.active_tour_id is None

    def test_set_visual_guidance_in_thinking_raises(self) -> None:
        s = SessionState()
        assert s.current_state == AgentStateV2.THINKING
        with pytest.raises(InvalidTransitionError):
            s.set_visual_guidance(True)

    def test_set_visual_guidance_without_tour_id(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        s.set_visual_guidance(True)
        assert s.visual_guidance_active is True
        assert s.active_tour_id is None


# ---------------------------------------------------------------------------
# SessionState — persistence round-trip
# ---------------------------------------------------------------------------


class TestSessionStatePersistence:
    def _assert_round_trip(self, s: SessionState) -> None:
        d = s.to_dict()
        restored = SessionState.from_dict(d)
        assert restored.current_state == s.current_state
        assert restored.interaction_timeout_s == s.interaction_timeout_s
        assert restored.cooldown_period_s == s.cooldown_period_s
        assert restored.visual_guidance_active == s.visual_guidance_active
        assert restored.active_tour_id == s.active_tour_id
        assert restored.thinking.cooldown_active == s.thinking.cooldown_active
        assert (
            restored.thinking.active_cooldown_period_s
            == s.thinking.active_cooldown_period_s
        )
        assert restored.proactive.user_clicked_option == s.proactive.user_clicked_option

    def test_round_trip_thinking_state(self) -> None:
        s = SessionState()
        self._assert_round_trip(s)

    def test_round_trip_thinking_with_cooldown(self) -> None:
        s = SessionState()
        s.thinking.start_cooldown(override_period_s=90.0)
        self._assert_round_trip(s)

    def test_round_trip_proactive_state(self) -> None:
        s = SessionState()
        s.transition_to_proactive("trig_1")
        s.proactive.user_clicked_option = True
        s.visual_guidance_active = True
        s.active_tour_id = "tour_x"
        self._assert_round_trip(s)

    def test_round_trip_reactive_state(self) -> None:
        s = SessionState()
        s.transition_to_reactive()
        s.visual_guidance_active = True
        s.active_tour_id = "tour_y"
        self._assert_round_trip(s)

    def test_from_dict_raises_on_wrong_version(self) -> None:
        s = SessionState()
        d = s.to_dict()
        d["_v"] = 99
        with pytest.raises(ValueError, match="Unknown SessionState snapshot version"):
            SessionState.from_dict(d)


# ---------------------------------------------------------------------------
# SessionState — record_tour_step
# ---------------------------------------------------------------------------


class TestRecordTourStep:
    def test_tour_step_in_proactive_resets_last_interaction_at(self) -> None:
        s = SessionState(interaction_timeout_s=10.0)
        s.transition_to_proactive("trig_1")
        old_ts = s.last_interaction_at
        s.record_tour_step()
        assert s.last_interaction_at >= old_ts

    def test_tour_step_in_proactive_resets_per_state_timer(self) -> None:
        s = SessionState(interaction_timeout_s=10.0)
        s.transition_to_proactive("trig_1")
        s.proactive._last_interaction_at_local -= 5.0
        s.record_tour_step()
        assert s.proactive.time_since_last_interaction_s == 0.0

    def test_tour_step_in_reactive_resets_last_interaction_at(self) -> None:
        s = SessionState(interaction_timeout_s=10.0)
        s.transition_to_reactive()
        old_ts = s.last_interaction_at
        s.record_tour_step()
        assert s.last_interaction_at >= old_ts

    def test_tour_step_in_reactive_resets_per_state_timer(self) -> None:
        s = SessionState(interaction_timeout_s=10.0)
        s.transition_to_reactive()
        s.reactive._last_interaction_at_local -= 5.0
        s.record_tour_step()
        assert s.reactive.time_since_last_interaction_s == 0.0

    def test_tour_step_in_thinking_does_not_crash(self) -> None:
        s = SessionState()
        assert s.current_state == AgentStateV2.THINKING
        s.record_tour_step()

    def test_tour_steps_keep_proactive_session_alive_without_chat(self) -> None:
        """Visual guidance keeps session alive even with zero chat interaction."""
        s = SessionState(interaction_timeout_s=0.05)
        s.transition_to_proactive("trig_1")
        s.visual_guidance_active = True
        assert not s.proactive.user_clicked_option

        for _ in range(3):
            s.record_tour_step()

        assert s.current_state == AgentStateV2.PROACTIVE

    def test_tour_step_without_chat_prevents_timeout(self) -> None:
        s = SessionState(interaction_timeout_s=0.05)
        s.transition_to_proactive("trig_1")

        time.sleep(0.03)
        s.record_tour_step()
        time.sleep(0.03)
        s.tick()

        assert s.current_state == AgentStateV2.PROACTIVE
