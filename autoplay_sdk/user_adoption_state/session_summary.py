"""Pure prompt-input builder for the onboarding-summary prompt.

Mirrors the ``build_tour_match_input`` pattern: this module only formats the
structured input for ``ONBOARDING_SUMMARY_PROMPT`` — it has no side effects and
never calls an LLM. The integration passes the result to ``acall_llm`` and feeds
the output back via ``on_session_end(..., summary=...)`` (or an injected
``summarizer``).
"""

from __future__ import annotations

import json

from autoplay_sdk.user_adoption_state.models import SessionSnapshot


def build_onboarding_summary_input(snapshot: SessionSnapshot) -> dict:
    """Assemble the structured input dict for ``ONBOARDING_SUMMARY_PROMPT``.

    Keys line up 1:1 with the prompt's ``{placeholders}``. List fields are
    JSON-encoded so they drop cleanly into the template.
    """
    return {
        "session_number": snapshot.session_number,
        "duration_minutes": round(snapshot.duration_s / 60.0, 1),
        "journey_state": snapshot.journey_state.value,
        "mastery_level": snapshot.mastery.level.value,
        "mastery_rating": snapshot.mastery.rating,
        "reached_onboarding_complete": snapshot.reached_onboarding_complete,
        "completion_rate": snapshot.completion_rate,
        "completed_workflow_ids_json": json.dumps(snapshot.completed_workflow_ids),
        "in_progress_workflow_ids_json": json.dumps(snapshot.in_progress_workflow_ids),
        "untouched_workflow_ids_json": json.dumps(snapshot.untouched_workflow_ids),
        "discovered_features_json": json.dumps(snapshot.discovered_features),
    }


__all__ = ["build_onboarding_summary_input"]
