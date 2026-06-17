"""Enums for the per-user adoption state.

These are intentionally simple ``str`` enums so they serialise directly into
the JSON snapshot persisted per user (see :mod:`autoplay_sdk.user_adoption_state.models`).
"""

from __future__ import annotations

from enum import Enum


class JourneyState(str, Enum):
    """Coarse lifecycle stage for a user.

    ONBOARDING : default for any new/unseen user; still learning the basics.
    ONBOARDED  : has cleared onboarding; uses the product on their own.
    """

    ONBOARDING = "onboarding"
    ONBOARDED = "onboarded"


class MasteryLevel(str, Enum):
    """Fine-grained competence band on the low...power-user spectrum.

    Independent of :class:`JourneyState` — a user can be ``ONBOARDED`` yet still
    ``INTERMEDIATE``, or ``ONBOARDING`` yet a fast ``PROFICIENT``.
    """

    NOVICE = "novice"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PROFICIENT = "proficient"
    POWER_USER = "power_user"


class WorkflowStatus(str, Enum):
    """Per-flow completion status as judged asynchronously from live activity.

    Completion is inferred by the agent from the live action stream (rarely a
    certain 1:1 event), so each target workflow carries a status rather than a
    yes/no flag.

    NOT_STARTED : no evidence the user has touched this flow.
    IN_PROGRESS : the agent sees partial activity toward the flow.
    COMPLETED   : the agent judges the flow done, with supporting evidence.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
