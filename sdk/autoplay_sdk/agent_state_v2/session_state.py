"""Agent session state v2 — 3-state FSM with per-state dataclasses.

SessionState (top level)
────────────────────────
  current_state         : AgentStateV2 – which of the 3 states is active
  last_interaction_at   : float  – monotonic ts; reset by any chatbot or tour interaction
  interaction_timeout_s : float  – default 20 s; session-level fallback
  cooldown_period_s     : float  – default 60 s; session-level fallback
  visual_guidance_active: bool   – True while a tour overlay is running (PROACTIVE or REACTIVE)
  active_tour_id        : str|None – ID of the running tour, used to look up per-tour timeouts
  thinking              : ThinkingState
  proactive             : ProactiveState
  reactive              : ReactiveState

ThinkingState
─────────────
  cooldown_active          : bool    – blocks proactive if True
  cooldown_started_at      : float   – monotonic ts of cooldown start
  active_cooldown_period_s : float|None – per-tour override set when a tour-induced
                                          timeout triggered the return to thinking

ProactiveState
──────────────
  user_clicked_option           : bool
  time_since_last_interaction_s : float – seconds since last interaction of ANY kind
                                          (chat, option click, reaction, or tour step)

ReactiveState
─────────────
  time_since_last_interaction_s : float – seconds since last interaction of ANY kind

Transition rules
────────────────
  thinking  → proactive   valid (blocked only if cooldown_active)
  thinking  → reactive    valid (cooldown does NOT block this)
  proactive → thinking    ONLY via tick() / _timeout_to_thinking() — never direct
  reactive  → thinking    ONLY via tick() / _timeout_to_thinking() — never direct
  proactive ↔ reactive    NEVER allowed
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from autoplay_sdk.agent_state_v2.types import AgentStateV2, InvalidTransitionError

if TYPE_CHECKING:
    from autoplay_sdk.proactive_triggers.tour_registry import TourRegistry

logger = logging.getLogger(__name__)

_EV_SNAPSHOT_INVALID = "agent_state_v2_snapshot_invalid"


# ---------------------------------------------------------------------------
# Per-state dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ThinkingState:
    """Cooldown tracking for the THINKING state.

    Fields
    ------
    cooldown_active          : bool       – blocks proactive if True
    cooldown_started_at      : float      – monotonic ts; compared against the resolved
                                            cooldown_period_s on each tick
    active_cooldown_period_s : float|None – tour-specific override; set when a tour-induced
                                            timeout triggered the return to thinking; None
                                            means use the session-level default
    """

    cooldown_active: bool = False
    cooldown_started_at: float = 0.0
    active_cooldown_period_s: float | None = None

    @property
    def can_go_proactive(self) -> bool:
        """True when no cooldown is in effect."""
        return not self.cooldown_active

    def start_cooldown(self, override_period_s: float | None = None) -> None:
        """Start a cooldown.

        Parameters
        ----------
        override_period_s:
            When set, this period is used instead of the session-level
            ``cooldown_period_s``. Pass the tour's ``cooldown_period_s`` here
            when the timeout was triggered during an active tour.
        """
        self.cooldown_active = True
        self.cooldown_started_at = time.monotonic()
        self.active_cooldown_period_s = override_period_s

    def clear_cooldown(self) -> None:
        self.cooldown_active = False
        self.cooldown_started_at = 0.0
        self.active_cooldown_period_s = None

    def tick(self, cooldown_period_s: float) -> None:
        """Auto-clear cooldown once the resolved period has elapsed.

        Uses ``active_cooldown_period_s`` when set, otherwise falls back to
        the session-level ``cooldown_period_s`` argument.
        """
        if self.cooldown_active:
            period = (
                self.active_cooldown_period_s
                if self.active_cooldown_period_s is not None
                else cooldown_period_s
            )
            if time.monotonic() - self.cooldown_started_at >= period:
                self.clear_cooldown()

    def to_dict(self) -> dict:
        return {
            "cooldown_active": self.cooldown_active,
            "cooldown_started_at": self.cooldown_started_at,
            "active_cooldown_period_s": self.active_cooldown_period_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ThinkingState:
        return cls(
            cooldown_active=d.get("cooldown_active", False),
            cooldown_started_at=d.get("cooldown_started_at", 0.0),
            active_cooldown_period_s=d.get("active_cooldown_period_s"),
        )


@dataclass
class ProactiveState:
    """Per-state data while in PROACTIVE_ASSISTANCE.

    Fields
    ------
    user_clicked_option           : bool  – True once the user taps a quick-reply option
    time_since_last_interaction_s : float – seconds since the last interaction of ANY kind:
                                           chat message, option click, reaction, or tour step.
                                           Visual guidance can fire proactively so this timer
                                           may advance without any chat activity.
    _last_interaction_at_local    : float – internal monotonic anchor (not persisted as-is)
    """

    user_clicked_option: bool = False
    time_since_last_interaction_s: float = 0.0

    _last_interaction_at_local: float = field(
        default_factory=time.monotonic, repr=False
    )

    def _reset_interaction_timer(self) -> None:
        self._last_interaction_at_local = time.monotonic()
        self.time_since_last_interaction_s = 0.0

    def record_user_interaction(self) -> None:
        """User sent a chat message."""
        self._reset_interaction_timer()

    def record_option_click(self) -> None:
        self.user_clicked_option = True
        self._reset_interaction_timer()

    def record_reaction(self) -> None:
        self._reset_interaction_timer()

    def record_tour_step(self) -> None:
        """Tour step — resets interaction timer even if user never opened chat."""
        self._reset_interaction_timer()

    def tick(self) -> None:
        """Refresh elapsed interaction timer."""
        self.time_since_last_interaction_s = (
            time.monotonic() - self._last_interaction_at_local
        )

    def to_dict(self) -> dict:
        return {
            "user_clicked_option": self.user_clicked_option,
            "time_since_last_interaction_s": self.time_since_last_interaction_s,
            "last_message_at": self._last_interaction_at_local,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProactiveState:
        obj = cls(
            user_clicked_option=d.get("user_clicked_option", False),
            time_since_last_interaction_s=d.get("time_since_last_interaction_s", 0.0),
        )
        obj._last_interaction_at_local = d.get("last_message_at", time.monotonic())
        return obj


@dataclass
class ReactiveState:
    """Per-state data while in REACTIVE_ASSISTANCE.

    Fields
    ------
    time_since_last_interaction_s : float – seconds since last interaction of ANY kind:
                                           chat message, option click, reaction, or tour step.
    _last_interaction_at_local    : float – internal monotonic anchor (not persisted as-is)
    """

    time_since_last_interaction_s: float = 0.0

    _last_interaction_at_local: float = field(
        default_factory=time.monotonic, repr=False
    )

    def _reset_interaction_timer(self) -> None:
        self._last_interaction_at_local = time.monotonic()
        self.time_since_last_interaction_s = 0.0

    def record_user_interaction(self) -> None:
        """User sent a chat message."""
        self._reset_interaction_timer()

    def record_reaction(self) -> None:
        self._reset_interaction_timer()

    def record_tour_step(self) -> None:
        """Tour step — resets interaction timer even if user never opened chat."""
        self._reset_interaction_timer()

    def tick(self) -> None:
        """Refresh elapsed interaction timer."""
        self.time_since_last_interaction_s = (
            time.monotonic() - self._last_interaction_at_local
        )

    def to_dict(self) -> dict:
        return {
            "time_since_last_interaction_s": self.time_since_last_interaction_s,
            "last_message_at": self._last_interaction_at_local,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ReactiveState:
        obj = cls(
            time_since_last_interaction_s=d.get("time_since_last_interaction_s", 0.0),
        )
        obj._last_interaction_at_local = d.get("last_message_at", time.monotonic())
        return obj


# ---------------------------------------------------------------------------
# Top-level SessionState
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Top-level v2 session FSM — 3 states with strict transition rules.

    Fields
    ------
    current_state         : AgentStateV2
    last_interaction_at   : float  – monotonic ts; reset by any chatbot or tour interaction
    interaction_timeout_s : float  – session-level fallback (default 20 s)
    cooldown_period_s     : float  – session-level fallback (default 60 s)
    visual_guidance_active: bool   – True while a tour overlay is running; only meaningful
                                     in PROACTIVE or REACTIVE
    active_tour_id        : str|None – ID of the currently running tour; used to look up
                                       per-tour timeouts from a TourRegistry
    thinking              : ThinkingState
    proactive             : ProactiveState
    reactive              : ReactiveState
    """

    current_state: AgentStateV2 = AgentStateV2.THINKING
    last_interaction_at: float = field(default_factory=time.monotonic)
    interaction_timeout_s: float = 20.0
    cooldown_period_s: float = 60.0
    visual_guidance_active: bool = False
    active_tour_id: str | None = None

    thinking: ThinkingState = field(default_factory=ThinkingState)
    proactive: ProactiveState = field(default_factory=ProactiveState)
    reactive: ReactiveState = field(default_factory=ReactiveState)

    _v: int = 1

    # ── tick ─────────────────────────────────────────────────────────────────

    def tick(self, tour_registry: TourRegistry | None = None) -> None:
        """Evaluate all timeout rules.

        Parameters
        ----------
        tour_registry:
            When provided, ``active_tour_id`` is resolved against the registry to
            obtain per-tour ``interaction_timeout_s`` and ``cooldown_period_s``
            overrides.  Falls back to the session-level defaults when the registry
            is absent or the tour is not found.

        Call on every incoming event and on a background pulse (e.g. every
        5 s) to catch silent timeouts.
        """
        now = time.monotonic()

        if self.current_state == AgentStateV2.THINKING:
            self.thinking.tick(self.cooldown_period_s)

        elif self.current_state in (AgentStateV2.PROACTIVE, AgentStateV2.REACTIVE):
            # Resolve per-tour timeout override.
            # active_tour_id stores the provider flow ID (user_tour_id), so look
            # up by user_tour_id rather than chip id.
            resolved_timeout = self.interaction_timeout_s
            resolved_cooldown = self.cooldown_period_s
            if tour_registry is not None and self.active_tour_id is not None:
                tour_def = tour_registry.get_by_user_tour_id(self.active_tour_id)
                if tour_def is not None:
                    resolved_timeout = tour_def.interaction_timeout_s
                    resolved_cooldown = tour_def.cooldown_period_s

            if now - self.last_interaction_at > resolved_timeout:
                self._timeout_to_thinking(cooldown_period_s=resolved_cooldown)
                return

            if self.current_state == AgentStateV2.PROACTIVE:
                self.proactive.tick()
            else:
                self.reactive.tick()

    # ── interaction recording ─────────────────────────────────────────────────

    def record_any_interaction(self) -> None:
        """Call on any chatbot or visual guidance activity."""
        self.last_interaction_at = time.monotonic()

    def record_user_interaction(self) -> None:
        """User sent a chat message."""
        self.record_any_interaction()
        if self.current_state == AgentStateV2.PROACTIVE:
            self.proactive.record_user_interaction()
        elif self.current_state == AgentStateV2.REACTIVE:
            self.reactive.record_user_interaction()

    def record_option_click(self) -> None:
        """User clicked a quick-reply chip."""
        self.record_any_interaction()
        if self.current_state == AgentStateV2.PROACTIVE:
            self.proactive.record_option_click()

    def record_reaction(self) -> None:
        """User added an emotional reaction."""
        self.record_any_interaction()
        if self.current_state == AgentStateV2.PROACTIVE:
            self.proactive.record_reaction()
        elif self.current_state == AgentStateV2.REACTIVE:
            self.reactive.record_reaction()

    def record_tour_step(self) -> None:
        """Any tour progress resets the interaction_timeout_s countdown.

        Counts as interaction in both PROACTIVE and REACTIVE — even when the user
        has never opened the chat (visual guidance can fire proactively).
        """
        self.record_any_interaction()
        if self.current_state == AgentStateV2.PROACTIVE:
            self.proactive.record_tour_step()
        elif self.current_state == AgentStateV2.REACTIVE:
            self.reactive.record_tour_step()

    # ── transitions ───────────────────────────────────────────────────────────
    #
    # Valid paths:
    #   thinking  → proactive  (trigger fires, cooldown_active must be False)
    #   thinking  → reactive   (user opens chat, always allowed)
    #   proactive → thinking   (interaction timeout only — automatic via tick())
    #   reactive  → thinking   (interaction timeout only — automatic via tick())
    #
    # proactive ↔ reactive direct transitions are NEVER allowed.

    def transition_to_reactive(self) -> None:
        """User opens the chatbot — only valid from THINKING.

        Raises
        ------
        InvalidTransitionError
            If called from PROACTIVE or REACTIVE.  The only way to exit those
            states is via interaction timeout (``tick()``).

        Notes
        -----
        Cooldown is cleared on success — a user initiating a chat cancels
        the proactive backoff period.
        """
        if self.current_state != AgentStateV2.THINKING:
            raise InvalidTransitionError(
                f"Cannot transition to REACTIVE from {self.current_state.value}. "
                "Must be in THINKING first. "
                "PROACTIVE and REACTIVE can only exit via interaction timeout."
            )
        self.record_any_interaction()
        self.current_state = AgentStateV2.REACTIVE
        self.reactive = ReactiveState()
        self.thinking.clear_cooldown()

    def transition_to_proactive(self, trigger_id: str) -> bool:
        """Agent fires a proactive trigger — only valid from THINKING.

        Parameters
        ----------
        trigger_id:
            Stable identifier of the trigger that fired (for logging).

        Returns
        -------
        bool
            ``True`` when the transition succeeded; ``False`` when blocked by
            an active cooldown (state is unchanged).

        Raises
        ------
        InvalidTransitionError
            If called from PROACTIVE or REACTIVE.
        """
        if self.current_state != AgentStateV2.THINKING:
            raise InvalidTransitionError(
                f"Cannot transition to PROACTIVE from {self.current_state.value}. "
                "Must be in THINKING first. "
                "PROACTIVE and REACTIVE can only exit via interaction timeout."
            )
        self.thinking.tick(self.cooldown_period_s)
        if not self.thinking.can_go_proactive:
            return False
        self.record_any_interaction()
        self.current_state = AgentStateV2.PROACTIVE
        self.proactive = ProactiveState()
        return True

    def _timeout_to_thinking(self, cooldown_period_s: float | None = None) -> None:
        """Return to THINKING after interaction timeout.

        This is the **sole** exit path from PROACTIVE and REACTIVE.  Always
        starts the cooldown so proactive cannot re-fire immediately.
        Clears ``visual_guidance_active`` and ``active_tour_id``.

        Private — called only by ``tick()``.  Never call directly.

        Parameters
        ----------
        cooldown_period_s:
            Override the session-level default for this particular cooldown.
            Pass the tour's ``cooldown_period_s`` when the timeout was triggered
            during an active tour.
        """
        self.current_state = AgentStateV2.THINKING
        self.visual_guidance_active = False
        self.active_tour_id = None
        self.thinking.start_cooldown(override_period_s=cooldown_period_s)

    # ── visual guidance ───────────────────────────────────────────────────────

    def set_visual_guidance(self, active: bool, tour_id: str | None = None) -> None:
        """Toggle visual guidance on this session.

        Parameters
        ----------
        active:
            ``True`` to start a tour; ``False`` to end it.
        tour_id:
            The tour identifier.  Only used when ``active=True``; ignored on
            deactivation.

        Raises
        ------
        InvalidTransitionError
            If called while in THINKING — visual guidance is only meaningful in
            PROACTIVE or REACTIVE.

        Notes
        -----
        Starting a tour (``active=True``) resets ``last_interaction_at``.
        Ending a tour (``active=False``) clears both ``visual_guidance_active``
        and ``active_tour_id``.
        """
        if self.current_state == AgentStateV2.THINKING:
            raise InvalidTransitionError(
                "set_visual_guidance() cannot be called in THINKING state. "
                "Visual guidance is only valid in PROACTIVE or REACTIVE."
            )
        if active:
            self.visual_guidance_active = True
            self.active_tour_id = tour_id
            self.record_any_interaction()
        else:
            self.visual_guidance_active = False
            self.active_tour_id = None

    # ── persistence ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "_v": self._v,
            "current_state": self.current_state.value,
            "last_interaction_at": self.last_interaction_at,
            "interaction_timeout_s": self.interaction_timeout_s,
            "cooldown_period_s": self.cooldown_period_s,
            "visual_guidance_active": self.visual_guidance_active,
            "active_tour_id": self.active_tour_id,
            "thinking": self.thinking.to_dict(),
            "proactive": self.proactive.to_dict(),
            "reactive": self.reactive.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> SessionState:
        if d.get("_v") != 1:
            logger.warning(
                "agent_state_v2: unknown snapshot version %r — cannot restore SessionState",
                d.get("_v"),
                extra={
                    "event_type": _EV_SNAPSHOT_INVALID,
                    "snapshot_version": d.get("_v"),
                },
            )
            raise ValueError(f"Unknown SessionState snapshot version: {d.get('_v')!r}")
        s = cls.__new__(cls)
        s._v = 1
        s.current_state = AgentStateV2(d["current_state"])
        s.last_interaction_at = d["last_interaction_at"]
        s.interaction_timeout_s = d.get("interaction_timeout_s", 20.0)
        s.cooldown_period_s = d.get("cooldown_period_s", 60.0)
        s.visual_guidance_active = d.get("visual_guidance_active", False)
        s.active_tour_id = d.get("active_tour_id")
        s.thinking = ThinkingState.from_dict(d.get("thinking", {}))
        s.proactive = ProactiveState.from_dict(d.get("proactive", {}))
        s.reactive = ReactiveState.from_dict(d.get("reactive", {}))
        return s
