"""Deterministic "explore-first" gate for the onboarding welcome.

This encodes the hard floor that guarantees a user is *never* interrupted too
early: the agent may only consider stepping in once the user has had a minimum
amount of time / exploration. Intelligent timing *on top of* this floor is the
LLM's job (see the onboarding welcome runner).

Pure and side-effect-free (per engineering rule "no side effects in builders").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autoplay_sdk.user_adoption_state.models import UserAdoptionState
from autoplay_sdk.user_adoption_state.types import JourneyState


@dataclass(frozen=True)
class ExplorationGateConfig:
    """Hard-floor thresholds for the onboarding welcome.

    role_allowlist        : roles eligible for proactive onboarding (empty = all).
    min_seconds_on_app    : minimum exploration time before we may interrupt.
    min_distinct_features : minimum distinct features/pages touched.
    welcome_cooldown_s    : minimum gap between proactive onboarding nudges.
    max_proactive_support : cap on total onboarding nudges per user.
    """

    role_allowlist: frozenset[str] = field(default_factory=frozenset)
    min_seconds_on_app: float = 60.0
    min_distinct_features: int = 3
    welcome_cooldown_s: float = 600.0
    max_proactive_support: int = 3


def evaluate_hard_gate(
    state: UserAdoptionState,
    *,
    now: float,
    seconds_on_app: float,
    distinct_features_seen: int,
    cfg: ExplorationGateConfig,
) -> tuple[bool, str]:
    """Return ``(passed, reason)`` for the explore-first floor.

    Blocks (returns ``False``) when the role is not allowlisted, the user has
    not explored enough yet, they are already fully onboarded, a cooldown is in
    effect, or the nudge cap has been reached. When ``True``, control passes to
    the LLM which decides whether now is the right moment and what to say.
    """
    if state.journey_state == JourneyState.ONBOARDED:
        return False, "already_onboarded"

    if cfg.role_allowlist:
        role = (state.role or "").strip()
        allowed = {r.strip().lower() for r in cfg.role_allowlist}
        if role.lower() not in allowed:
            return False, f"role_not_allowed:{role or 'unknown'}"

    onboarding = state.onboarding

    if onboarding.proactive_support_count >= cfg.max_proactive_support:
        return False, "nudge_cap_reached"

    last_welcome = onboarding.last_welcome_at
    if last_welcome is not None and (now - last_welcome) < cfg.welcome_cooldown_s:
        return False, "within_cooldown"

    if seconds_on_app < cfg.min_seconds_on_app:
        return False, "exploring_min_time_not_met"

    if distinct_features_seen < cfg.min_distinct_features:
        return False, "exploring_min_features_not_met"

    return True, "ok"
