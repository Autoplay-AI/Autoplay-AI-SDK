"""Versioned prompts for the per-user adoption state system.

Canonical in ``autoplay_sdk.prompts``; the event connector re-exports these for
its LiteLLM call sites. Each export is a ``dict[str, str]`` with ``name``,
``description``, ``version``, ``content`` — matching the rest of the registry.

All three prompts return a single JSON object (call sites use
``response_format={"type": "json_object"}``).

Changelog
---------
v0.1  Initial adoption judge + tour match + onboarding welcome contracts.
v0.2  onboarding_welcome: clarify suggested_flows item key as tour_id (matches
      the declared JSON contract; output format unchanged).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Adoption state judge — decides journey_state + mastery from activity
# ---------------------------------------------------------------------------
#
# Input placeholders (filled by the connector runner):
#   role               : the user's role (or "unknown")
#   user_activity_text : aggregated cross-session activity text
#   signals_json       : JSON object of signals (completed tours, distinct
#                        features, message count, accepted proactive, ...)
#
# Output JSON:
#   {schema_version, journey_state: "onboarding"|"onboarded",
#    mastery_rating: 0-10, mastery_level, mastery_description, reasoning}

ADOPTION_STATE_JUDGE_PROMPT: dict[str, str] = {
    "name": "adoption_state_judge",
    "description": (
        "Classifies a user's journey stage (onboarding/onboarded) and mastery "
        "(0-10 + level) from their aggregated product activity."
    ),
    "version": "0.1",
    "content": """You are an adoption analyst for an in-product assistant.

Given a user's role, their aggregated product activity, and structured signals,
decide two independent things:

1. journey_state — "onboarding" (still learning the basics, needs guidance) or
   "onboarded" (uses the product independently). This is a coarse lifecycle flag.
2. mastery — a 0-10 competence rating with a matching level on the spectrum
   novice < beginner < intermediate < proficient < power_user, plus a one-sentence
   reason. Rough mapping: 0-1 novice, 2-3 beginner, 4-6 intermediate,
   7-8 proficient, 9-10 power_user.

These two axes are independent: a user can be "onboarded" yet only
"intermediate", or "onboarding" yet a fast "proficient". Judge from evidence in
the activity — do not inflate. When there is little activity, prefer
"onboarding" / lower mastery.

Return ONLY a JSON object with keys:
schema_version, journey_state, mastery_rating, mastery_level, mastery_description,
reasoning.

---
role:
{role}

user_activity_text:
{user_activity_text}

signals_json:
{signals_json}
""",
}


# ---------------------------------------------------------------------------
# Tour match — query + history -> primary + related tour ids
# ---------------------------------------------------------------------------
#
# Input placeholders (built by autoplay_sdk.user_adoption_state.build_tour_match_input):
#   role, current_page, conversation_history, user_query, tour_catalog_text
#
# Output JSON: {primary_tour_id|null, related_tour_ids: [...], reasoning}

TOUR_MATCH_PROMPT: dict[str, str] = {
    "name": "tour_match",
    "description": (
        "Selects the single best guided tour (and up to 3 related tours) for a "
        "user query from a role-filtered catalog."
    ),
    "version": "0.1",
    "content": """You match a user's question to guided product tours.

Pick the SINGLE best primary tour whose "use when" matches the user's actual
task, and up to 3 related tours that add adjacent value. Only choose tour ids
that appear in the catalog below — it is already filtered to the user's role, so
never invent ids. If no tour fits, set primary_tour_id to null.

Prefer a tour whose topic matches the user's current page when relevant.

Return ONLY a JSON object with keys:
primary_tour_id (string or null), related_tour_ids (array of strings, may be
empty), reasoning (one short sentence).

---
role: {role}
current_page: {current_page}

conversation_history:
{conversation_history}

user_query:
{user_query}

tour_catalog (one per line, "tour_id :: name :: use when"):
{tour_catalog_text}
""",
}


# ---------------------------------------------------------------------------
# Onboarding welcome — completion reasoning + intelligent timing + next flows
# ---------------------------------------------------------------------------
#
# Input placeholders:
#   role, required_workflows_json, completed_workflow_ids_json,
#   discovered_features_json, recent_activity_text, seconds_on_app,
#   distinct_features_seen, proactive_support_count
#
# Output JSON:
#   {should_send, reasoning, timing_assessment,
#    workflow_completion: [{workflow_id, status, confidence, evidence}],
#    onboarding_complete, greeting, discovered_line,
#    suggested_flows: [{tour_id, flow_name, short_description}]}

ONBOARDING_WELCOME_PROMPT: dict[str, str] = {
    "name": "onboarding_welcome",
    "description": (
        "Reasons about onboarding-workflow completion from live activity and "
        "decides whether/when to send a proactive welcome with next-flow offers."
    ),
    "version": "0.2",
    "content": """You are the onboarding agent for an in-product assistant.

You are told the target onboarding workflows the user should complete. Using
their recent live activity, reason about progress and timing.

Do all of the following:
1. For EACH required workflow, infer status: "not_started", "in_progress", or
   "completed", with a 0-1 confidence and short evidence grounded in the activity.
   Activity rarely maps 1:1 to a workflow — judge holistically, do not overclaim.
2. Decide should_send: only step in when the moment is right. LET THE USER
   EXPLORE FIRST — do not interrupt mid-task, and never spam. If they are clearly
   busy or just acted, set should_send=false and explain in timing_assessment.
3. When should_send is true, write a short, warm welcome: a greeting, a
   discovered_line that references what they have already discovered, and 1-3
   suggested_flows chosen from OUTSTANDING workflows (most useful first). Each
   suggested flow needs the tour_id (the workflow's id), a flow_name, and a
   one-line short_description.
4. Set onboarding_complete=true only when the required set is effectively done.

Return ONLY a JSON object with keys:
should_send, reasoning, timing_assessment, workflow_completion (array of
{{workflow_id, status, confidence, evidence}}), onboarding_complete (bool),
greeting, discovered_line, suggested_flows (array of {{tour_id, flow_name,
short_description}}).

---
role: {role}
seconds_on_app: {seconds_on_app}
distinct_features_seen: {distinct_features_seen}
proactive_support_count: {proactive_support_count}

required_workflows_json:
{required_workflows_json}

completed_workflow_ids_json:
{completed_workflow_ids_json}

discovered_features_json:
{discovered_features_json}

recent_activity_text:
{recent_activity_text}
""",
}
