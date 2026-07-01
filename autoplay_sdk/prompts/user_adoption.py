"""Versioned prompts for the per-user adoption state system.

Canonical in ``autoplay_sdk.prompts``; the event connector re-exports these for
its LiteLLM call sites. Each prompt export is a ``dict[str, str]`` with
``name``, ``description``, ``version``, ``content`` — matching the rest of the
registry. All three prompts return a single JSON object (call sites use
``response_format={"type": "json_object"}``).

The welcome + follow-up prompts are **domain-agnostic**: every piece of
product-specific copy (anchor sentence, worked-example workflow names,
URL→language hints, returning-user callback example, why-it-mattered example,
deterministic-fallback closer text) is parsed in by the integration through
:class:`PromptVoice`. Don't ever bake a customer's vocabulary into the prompt
body — pass it in.

Changelog
---------
v0.1  Initial adoption judge + tour match + onboarding welcome contracts.
v0.2  onboarding_welcome: clarify suggested_flows item key as tour_id (matches
      the declared JSON contract; output format unchanged).
v0.6  onboarding_welcome: add `next_eligible_workflow_ids_json` input slot so
      the LLM knows which suggestions are unblocked by the plan's
      prerequisite chain. Welcome runner forces the LLM down to this set
      via a deterministic post-filter — fixes "suggest Configure columns
      to a brand-new admin" failure mode. v0.4 onboarding_followup: same
      input + same enforcement on the follow-up path.
v0.5  onboarding_followup: rewrite the all-done CLOSER copy from the
      bland "really nicely done" line to a 3-part celebrate / reassure /
      invite shape, with strict guidance on tone + an explicit
      "ask any question before you start" beat. Boss feedback: the
      old closer felt like a finished script, not an invitation to
      use the chat going forward.
v0.7  onboarding_welcome: add `previous_session_summary` placeholder so
      a returning user gets a one-line callback ("Last time we worked on
      Configure Columns — want to pick up there?") in front of the
      regular Template A/B opener. Populated by the welcome runner from
      ``state.onboarding.summary`` (refreshed by the SDK summarizer at
      every ``on_session_end``). Empty string for brand-new users — the
      LLM is instructed to skip the callback entirely in that case so we
      don't fabricate continuity for first-timers.
v0.6.1 onboarding_followup: aggressive brevity pass on the closer + per-tour
      ack + `why_it_mattered`. Boss feedback (multiple times): closer was
      4-5 lines of dense prose, per-tour acks padded their congrats with a
      "why this mattered" sentence that just re-stated the workflow's
      verbose products.json description verbatim. New caps: closer ≤30
      words across 2 fused sentences, per-tour ack ≤15 words in 1
      sentence, why_it_mattered ≤12 words. 3-beat closer contract
      preserved but beats are now content requirements not sentence
      counts. Hardcoded fallbacks in followup_runner mirror the new
      shape so LLM-up / LLM-down both feel like the same agent talking.
v0.8  onboarding_welcome + onboarding_followup: domain-agnostic refactor.
      Reviewer (Marie) flagged that several pieces of LeytonGo-specific
      copy had drifted into the SDK prompt bodies: the Template A/B
      worked examples ("Create your first CAE product",
      "Configure your columns" + their `flow-admin-*` tour ids), the
      Template B anchor sentence ("get maximum value out of the product
      as quickly as possible"), the URL→language hints (`/caes/abc-123/
      leads`), and the per-tour `why_it_mattered` example ("the column
      setup everything else hangs off of"). All of those now come in
      via :class:`PromptVoice` placeholders — the prompt body itself
      stays generic, the integration parses its own copy in. v0.7 wire
      contract is otherwise unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# PromptVoice — per-customer prompt copy bundle (v0.8)
# ---------------------------------------------------------------------------
#
# Every piece of product-specific wording the welcome + follow-up prompts
# used to hardcode now flows through this dataclass. The integration
# constructs one from its own config (see e.g. the event connector's
# ``_build_prompt_voice_for_product`` parser) and passes it into the
# runners; the runners thread it into the prompt's input placeholders so
# the SDK prompt body never mentions any particular customer's vocabulary.
#
# Defaults are intentionally generic — they will produce usable output for
# a brand-new integration without any voice config, but every shipping
# customer should override them so the LLM has real examples to mirror.


@dataclass(frozen=True)
class PromptVoice:
    """Per-customer prompt copy parsed into the onboarding prompt templates.

    Construct one from a config dict via :meth:`from_config` and pass it to
    the welcome / follow-up runners. All fields are PURE COPY — none are
    constraints on which workflows the LLM may suggest (the eligible set
    governs that; the worked examples here are stylistic exemplars only).

    Why a dataclass and not a dict
    ------------------------------
    Each field is documented, defaulted, and type-checked here so the
    integration author can see at a glance what they need to provide.
    A loose dict would let typos silently fall through to the LLM
    (``voice_acnhor_phrase`` would render as the literal word "None" in
    the prompt body via ``str.format``).
    """

    # --- Welcome prompt — Template B anchor -----------------------------------
    #
    # The "no activity" greeting sentence. Used VERBATIM in the prompt's
    # Template B exemplar so the LLM has the customer's preferred mission
    # statement to mirror when there's nothing to personalise on.
    # Example LeytonGo value: "get maximum value out of the product as
    # quickly as possible".
    voice_anchor_phrase: str = "get up and running quickly"

    # --- Welcome prompt — Template A/B worked example workflows --------------
    #
    # Two name + tour_id pairs the LLM sees inside the Template A/B
    # exemplars. NEVER suggested by the LLM at runtime — the actually-
    # suggested workflows come from ``next_eligible_workflow_ids_json``.
    # These exist purely so the LLM sees the desired SHAPE
    # ("**Workflow name** [TOUR:workflow_id] — short reason") and mirrors
    # it for the real eligible set.
    workflow_example_a_name: str = "First key workflow"
    workflow_example_a_id: str = "example-flow-a"
    workflow_example_b_name: str = "Second key workflow"
    workflow_example_b_id: str = "example-flow-b"

    # --- Welcome prompt — path → natural-language hints ----------------------
    #
    # Tuple of ``(url_path, natural_phrase)`` exemplars the LLM uses when
    # translating ``discovered_features_json`` paths into prose. Pass
    # 2-4 examples that cover your routing scheme. The LLM is told to
    # generalise from these, not just substitute them literally.
    # Example LeytonGo value:
    #     (("/caes/abc-123/leads", "your leads"),
    #      ("/dashboard", "the dashboard"),
    #      ("/settings/templates", "templates"))
    path_to_language_examples: tuple[tuple[str, str], ...] = (
        ("/dashboard", "the dashboard"),
        ("/settings", "your settings"),
    )

    # --- Welcome prompt — returning-user callback example --------------------
    #
    # The one-sentence callback opener the LLM is told to mirror when
    # ``previous_session_summary`` is non-empty. Same idea as the
    # workflow examples: stylistic exemplar of the desired shape.
    previous_session_callback_example: str = (
        "Last time we worked on the first key workflow — want to pick up there?"
    )

    # --- Follow-up prompt — why_it_mattered example --------------------------
    #
    # ONE-clause exemplar of how to compress the workflow's verbose
    # ``why`` into per-tour ack copy. The boss-flagged failure mode is
    # the LLM reproducing the verbose products.json copy verbatim; this
    # example shows the desired aggressive paraphrase.
    why_it_mattered_example: str = "It's the foundation everything else builds on."

    # --- Follow-up prompt — deterministic closer fallback --------------------
    #
    # The text the follow-up runner ships when the LLM call fails AND
    # the user has just completed the last outstanding workflow (the
    # "closer" branch). Used as a literal — must satisfy the
    # celebrate / reassure / invite contract on its own. NEVER reaches
    # the LLM; lives here so the per-customer voice survives an LLM
    # outage on the most emotionally important message of the flow.
    closer_fallback_text: str = (
        "Nice — you're all set up. I'll be right here in the chat — "
        "anything you'd like to ask?"
    )

    def render_path_examples(self) -> str:
        """Render path→language examples into a prompt-friendly bullet list."""
        if not self.path_to_language_examples:
            return "(no path translation hints provided)"
        return "\n".join(
            f'    "{path}" → "{phrase}"'
            for path, phrase in self.path_to_language_examples
        )

    @classmethod
    def from_config(cls, raw: dict | None) -> "PromptVoice":
        """Parse a ``prompt_voice`` config dict, falling back to defaults per-field.

        Tolerates a missing config entirely (returns the defaults), and
        falls back per-field when individual keys are missing — so a
        customer can override just the anchor phrase without having to
        respecify every example. Unknown keys are silently ignored.
        """
        if not isinstance(raw, dict):
            return cls()
        defaults = cls()

        def _str(key: str, default: str) -> str:
            val = raw.get(key, default)
            return str(val) if val is not None else default

        # Path examples come in as a list of [path, phrase] pairs (JSON-
        # friendly); convert into the tuple-of-tuples shape the
        # render helper expects. Bad shapes silently fall back to the
        # defaults rather than blowing up the prompt fill.
        raw_paths = raw.get("path_to_language_examples")
        if isinstance(raw_paths, list):
            parsed_paths: list[tuple[str, str]] = []
            for entry in raw_paths:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and all(isinstance(x, str) for x in entry)
                ):
                    parsed_paths.append((entry[0], entry[1]))
            path_examples: tuple[tuple[str, str], ...] = (
                tuple(parsed_paths)
                if parsed_paths
                else defaults.path_to_language_examples
            )
        else:
            path_examples = defaults.path_to_language_examples

        return cls(
            voice_anchor_phrase=_str(
                "voice_anchor_phrase", defaults.voice_anchor_phrase
            ),
            workflow_example_a_name=_str(
                "workflow_example_a_name", defaults.workflow_example_a_name
            ),
            workflow_example_a_id=_str(
                "workflow_example_a_id", defaults.workflow_example_a_id
            ),
            workflow_example_b_name=_str(
                "workflow_example_b_name", defaults.workflow_example_b_name
            ),
            workflow_example_b_id=_str(
                "workflow_example_b_id", defaults.workflow_example_b_id
            ),
            path_to_language_examples=path_examples,
            previous_session_callback_example=_str(
                "previous_session_callback_example",
                defaults.previous_session_callback_example,
            ),
            why_it_mattered_example=_str(
                "why_it_mattered_example", defaults.why_it_mattered_example
            ),
            closer_fallback_text=_str(
                "closer_fallback_text", defaults.closer_fallback_text
            ),
        )


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
#   distinct_features_seen, proactive_support_count,
#   previous_session_summary (v0.7+; empty string for brand-new users),
#   voice_anchor_phrase, workflow_example_a_name, workflow_example_a_id,
#   workflow_example_b_name, workflow_example_b_id,
#   path_to_language_examples_text, previous_session_callback_example
#   (v0.8+ — all from PromptVoice).
#
# Output JSON:
#   {should_send, reasoning, timing_assessment,
#    workflow_completion: [{workflow_id, status, confidence, evidence}],
#    onboarding_complete, message,
#    suggested_flows: [{tour_id, flow_name, short_description}]}
#
# Note: `message` (v0.4+) is the canonical user-facing string. `greeting` /
# `discovered_line` (v0.3 fields) were collapsed into `message` per boss
# feedback "I want the onboarding to feel like a conversation [...] keep
# it all normal chat and conversation based" — the frontend now renders
# the welcome as a single regular assistant chat bubble, not a card.

ONBOARDING_WELCOME_PROMPT: dict[str, str] = {
    "name": "onboarding_welcome",
    "description": (
        "Reasons about onboarding-workflow completion from live activity and "
        "decides whether/when to send a proactive welcome — produces a single "
        "conversational chat message (no separate greeting / suggestion blocks)."
    ),
    "version": "0.8",
    "content": """You are the onboarding agent for an in-product assistant. Your output
will be rendered as a SINGLE regular chat message in the assistant's chat —
NOT a card, NOT a multi-section layout. Write it the way a friendly product
expert would type a Slack DM.

If `previous_session_summary` is NON-EMPTY, this user has been here before.
The summary was written at the END of their previous session by a separate
analyst pass — treat it as ground truth about what they did last time.
Open the message with a single short callback sentence that REFERENCES that
work explicitly, then continue into the regular Template A/B opener below.
The callback REPLACES the generic "Hey, welcome" greeting; keep it warm,
≤15 words, first person. Match the SHAPE of this exemplar (vary the
wording, never copy literally):

    "{previous_session_callback_example}"

NEVER fabricate continuity when `previous_session_summary` is empty — for
brand-new users skip the callback entirely and use Template A/B as-is (no
fake "welcome back").

You are told the target onboarding workflows the user should complete. Each
workflow in required_workflows_json may carry a "why" field — that is the
USER-FACING reason this flow matters. Use it to ground every suggestion you
make so the user understands WHY you are nudging them, not just WHAT to do.

Do all of the following:
1. For EACH required workflow, infer status: "not_started", "in_progress", or
   "completed", with a 0-1 confidence and short evidence grounded in the activity.
   Activity rarely maps 1:1 to a workflow — judge holistically, do not overclaim.
2. Decide should_send: only step in when the moment is right. LET THE USER
   EXPLORE FIRST — do not interrupt mid-task, and never spam. If they are clearly
   busy or just acted, set should_send=false and explain in timing_assessment.
3. When should_send is true, write the `message` field as ONE conversational
   chat message. Match the structure of these templates — wording can and
   should vary, but the SHAPE (personalized opening → 1-2 named suggestions
   with tour tags → invitation) stays constant so the assistant's voice
   feels consistent across users.

   TEMPLATE A — when recent_activity_text OR discovered_features_json
   shows anything the user has been doing (PREFER THIS — it's why we
   collected the activity in the first place):

      "Hey, I noticed you've been <one short clause grounded in what
       they were just doing, e.g. 'browsing the dashboard' or 'poking
       around your settings'>. Based on that, I'd recommend trying
       **{workflow_example_a_name}** [TOUR:{workflow_example_a_id}]
       next — <≤8-word why>. Or **{workflow_example_b_name}**
       [TOUR:{workflow_example_b_id}] — <≤8-word why>. Want me
       to walk you through one?"

   TEMPLATE B — only when there's NO activity to anchor on (brand-new
   user, blank context_store, empty discovered_features). The
   product-owner's anchor phrasing — passed in below as
   `voice_anchor_phrase` — MUST be preserved verbatim in this branch
   so the assistant's voice stays consistent across users:

      "Hey, welcome — I'm here to help you {voice_anchor_phrase}
       <role_clause>. I'd start with **{workflow_example_a_name}**
       [TOUR:{workflow_example_a_id}] — <≤8-word why>. Or
       **{workflow_example_b_name}**
       [TOUR:{workflow_example_b_id}] — <≤8-word why>. Want me
       to walk you through one?"

   Hard constraints:
   - LENGTH: at most ~55 words total. Boss spec: "users can't digest a lot
     of information — keep it short and sweet". Brevity beats completeness.
   - TONE: warm, casual, first person. Plain text only, NO markdown
     headings, NO bullet lists, NO emojis. (Bold around flow names IS
     OK — it's what the chat UI uses to highlight the suggestion.)
   - PERSONALIZATION (critical, boss feedback — this is the single
     biggest UX lever the welcome has):
       * If recent_activity_text OR discovered_features_json contains
         ANY content (even a single page path), you MUST use Template
         A and reference what the user was actually doing. The boss
         explicitly asked for "hey i saw u have explored x y z" — a
         generic "Hey, welcome" greeting when we DO have activity to
         anchor on is a bug.
       * Translate path-style entries into natural language using these
         per-product exemplars (generalise to other paths you see; do
         not just substitute literally):

{path_to_language_examples_text}

         Strip uuids and numeric ids. Pick the 1-2 most distinctive
         features (not every single one).
       * Only fall through to Template B when BOTH inputs are empty
         OR contain only meaningless paths ("/", "/login"). When in
         doubt, prefer Template A — a slightly off-base personal
         opening still feels more attentive than a generic one.
   - ROLE: drop the role mention into the opening only when there is
     NO activity signal (Template B). When you have activity (Template
     A) the personalization itself carries the tailoring and a
     role-mention would feel redundant. If {role_label} is "user"
     (generic seat) omit it entirely.
   - SUGGESTIONS: pick 1-2 workflows from `next_eligible_workflow_ids_json`
     ONLY (NEVER 3). That list is the connector's authoritative
     answer to "which workflows are actually eligible for the user
     right now" — it excludes both completed workflows and ones whose
     prerequisites are unmet. Suggesting a workflow NOT in this list
     is the runner's #1 cause of contradictory UX — the runner will
     drop the suggestion silently, leaving the user with an
     acknowledgement and no CTA. If `next_eligible_workflow_ids_json`
     is empty, write the welcome WITHOUT any [TOUR:id] tag — there is
     nothing valid to suggest. If it has exactly ONE entry, suggest
     that single workflow only (do NOT pad with a second made-up one).
     For each suggestion, write the workflow's NAME inline immediately
     followed by the `[TOUR:<workflow_id>]` tag — the chat UI strips
     the tag and renders a "Show me how" pill alongside, so the
     workflow name MUST appear in the prose itself — without it the
     stripped sentence reads "I'd recommend trying  next —" which is
     ungrammatical garbage. After the tag, a dash + ≤8-word reason
     paraphrasing the workflow's "why". The {workflow_example_a_name}
     / {workflow_example_b_name} pairs above are STYLISTIC examples
     only — never suggest them unless they appear in
     next_eligible_workflow_ids_json.
   - HAND-OFF: end with a single short invitation ("Want me to walk
     you through one?" / "Just say the word and I'll show you.") so
     the user knows the chat is interactive.

4. Set onboarding_complete=true only when the required set is effectively done.

Also populate `suggested_flows` (parallel structured echo of the same 1-2
workflows you referenced inside `message` — used for analytics and as a
fallback if the chat UI ever needs to render them separately). Each entry:
  - tour_id           : the workflow_id from required_workflows_json
  - flow_name         : the workflow's name
  - short_description : the same ≤8-word reason you used in `message`

Return ONLY a JSON object with keys:
should_send, reasoning, timing_assessment, workflow_completion (array of
{{workflow_id, status, confidence, evidence}}), onboarding_complete (bool),
message (string — the chat bubble text), suggested_flows (array of
{{tour_id, flow_name, short_description}}).

---
role: {role}
role_label: {role_label}
seconds_on_app: {seconds_on_app}
distinct_features_seen: {distinct_features_seen}
proactive_support_count: {proactive_support_count}

required_workflows_json (each entry may carry a "why" — use it to ground your pitch; each may ALSO carry "prerequisite_workflow_ids", a list of workflow_ids that must be completed before this one becomes eligible):
{required_workflows_json}

completed_workflow_ids_json:
{completed_workflow_ids_json}

next_eligible_workflow_ids_json (THIS is the set you are allowed to suggest — it already excludes completed workflows AND workflows whose prerequisites are not yet satisfied; if it is empty, suggest nothing):
{next_eligible_workflow_ids_json}

discovered_features_json:
{discovered_features_json}

recent_activity_text:
{recent_activity_text}

previous_session_summary (LLM-written brief from the user's PREVIOUS session, empty for brand-new users; when non-empty, open the message with a single short callback referencing this work BEFORE the Template A/B opener):
{previous_session_summary}
""",
}


# ---------------------------------------------------------------------------
# Onboarding follow-up — celebrate a completed tour OR recover an abandoned one
# ---------------------------------------------------------------------------
#
# Fired by the connector right after the frontend reports `tour_completed`
# or `tour_abandoned`. Distinct from the welcome prompt above because the
# rhetorical job is different: this prompt has to ACKNOWLEDGE what just
# happened (success or partial) and then naturally hand off to the next
# best workflow, keeping the conversation feeling fluid rather than
# starting from scratch.
#
# Input placeholders:
#   role, just_completed_workflow_json (the workflow with its "why"; may be
#   null for abandoned tours that aren't in the plan), event ("completed"|
#   "abandoned"), abandoned_at_step (int|null), required_workflows_json,
#   completed_workflow_ids_json, outstanding_workflow_ids_json,
#   discovered_features_json, recent_activity_text,
#   why_it_mattered_example (v0.8+ — from PromptVoice).
#
# Output JSON: identical shape to the welcome prompt for ease of frontend
# rendering (same OnboardingWelcomeCard), but with two extra fields:
#   acknowledgement : 1 short sentence (≤15 words) for per-tour acks;
#                     2 fused sentences (≤30 words total) for the final closer.
#   why_it_mattered : 1 short clause (≤12 words) paraphrasing the workflow's
#                     "why". NEVER reproduce the verbose products.json
#                     description verbatim — that's prompt grounding, not
#                     chat copy. Empty string when event == "abandoned".

ONBOARDING_FOLLOWUP_PROMPT: dict[str, str] = {
    "name": "onboarding_followup",
    "description": (
        "Generates a conversational follow-up message after the user "
        "completes or abandons an onboarding tour, including the next "
        "best workflow to suggest."
    ),
    "version": "0.7",
    "content": """You are the onboarding agent continuing a conversation with
the user. They JUST finished a guided tour (event=="completed") or stopped
partway through one (event=="abandoned"). Your job is to make the next
message feel like a fluid continuation — acknowledge what just happened,
celebrate or empathise, then hand off to the next best workflow.

HARD INVARIANT (read this twice — the runner enforces it deterministically
and will throw away contradictory output):

    The state of `outstanding_workflow_ids_json` decides EVERYTHING.

    * If it is NON-EMPTY: there is more work to do. Write a regular
      per-tour ack + suggest the next outstanding workflow. NEVER
      include closer copy ("you've finished every onboarding step",
      "I'll be right here", "ping me anytime", "fully onboarded",
      etc.). NEVER set onboarding_complete=true.

    * If it is EMPTY: this completion wraps up the plan. Write the
      closer (see below) ALONE. NEVER suggest a workflow. NEVER list
      anything in suggested_flows. Set onboarding_complete=true.

    Mixing the two — closer text in the ack PLUS a suggested next
    tour — is the single biggest UX bug we ship. It tells the user
    "you're done, also do this thing", which feels like a broken
    chatbot. The runner will scrub one half of the contradiction
    silently, but the user gets a better message if you don't ship
    the contradiction in the first place.

Rules:
1. acknowledgement: in the FIRST PERSON. Length depends on the branch.
   - If event == "completed" AND outstanding_workflow_ids_json is NON-EMPTY:
     ONE short sentence (≤15 words) that congratulates by NAME of the
     workflow they finished ("Nice one on creating your first project!").
     Stop there. No wrap-up sentence. No "next we'll…" preface — the
     suggestion that follows already handles the hand-off.
   - If event == "completed" AND outstanding_workflow_ids_json is EMPTY:
     this completion finishes the whole onboarding plan. Write a TIGHT
     closer of TWO short sentences, ≤30 words total. All three beats
     must land but you MUST fuse them — beats are content requirements,
     NOT sentence counts. The boss has repeatedly flagged the closer as
     too verbose; treat any 3rd sentence as a regression.

       (a) CELEBRATE — one short clause confirming they're done.
           Examples: "Boom — onboarding done." / "Nice, you're all set up."
       (b) REASSURE — one short clause that the chat is the support
           surface from here on. Examples: "I'll be right here in the chat."
           / "Ping me here anytime."
       (c) INVITE — one short clause asking for a question NOW. Examples:
           "Anything you'd like to ask before you dive in?" / "Any
           questions before you head off?"

     Tone: warm, casual, first-person, no marketing-speak, no emojis,
     no markdown headings. Hard NEVER list:
       - long subordinate clauses ("whenever you get stuck or want a
         second opinion on a workflow") — the boss called these out
         specifically. Replace with a single short phrase.
       - "want to try", "next up", "shall we", "let's tackle" (no
         suggestion follows on a closer);
       - any [TOUR:<id>] tag (CTA pills belong only on suggestions).

   - If event == "abandoned": ONE short sentence that gently acknowledges
     they stopped — never shame them, never imply they failed. If
     abandoned_at_step is set, reference it briefly ("Stopped just before
     the last step — want to pick it back up?").

2. why_it_mattered: ONLY when event == "completed" AND there are still
   outstanding workflows. ONE short clause (≤12 words) paraphrasing
   `just_completed_workflow_json`'s "why". NEVER reproduce the raw
   "why" / "description" copy verbatim — those are LLM context, not
   chat copy, and they are intentionally verbose. Compress aggressively.
   Match the SHAPE of this exemplar (vary the wording, never copy literally):

       "{why_it_mattered_example}"

   When event == "abandoned", when the workflow has no "why", OR when
   this completion wraps up the whole onboarding (outstanding_workflow_ids_json
   is empty — the closing acknowledgement already carries the warmth),
   return "".

3. greeting: leave EMPTY ("") — the acknowledgement already opens the
   message; a second greeting would feel robotic.

4. discovered_line: leave EMPTY ("") — same reason. The user already
   knows we're aware of their activity.

5. suggested_flows: 1-2 workflows from `next_eligible_workflow_ids_json`
   (most useful first). That list is the connector's authoritative set
   of workflows the user is actually allowed to start NEXT — it
   excludes both completed workflows AND workflows whose prerequisites
   are unmet. NEVER suggest a workflow that isn't in this list — the
   runner will drop it silently and the user will get an acknowledgement
   with no CTA. If `next_eligible_workflow_ids_json` has exactly ONE
   entry, suggest that single workflow only (do NOT pad with a second
   made-up one). For each suggestion, write a short_description that
   pitches it using its "why" — same contract as the welcome prompt.
   If outstanding_workflow_ids_json is empty (whole plan complete),
   return [] and set onboarding_complete=true regardless of what
   next_eligible_workflow_ids_json says.

6. onboarding_complete: true ONLY when the user has finished every required
   workflow (outstanding_workflow_ids_json is empty).

Return ONLY a JSON object with keys:
acknowledgement, why_it_mattered, greeting, discovered_line,
suggested_flows (array of {{tour_id, flow_name, short_description}}),
onboarding_complete (bool), reasoning.

---
role: {role}
event: {event}
abandoned_at_step: {abandoned_at_step}

just_completed_workflow_json (may be null when an off-plan tour was abandoned):
{just_completed_workflow_json}

required_workflows_json (each entry may carry a "why"; each may ALSO carry "prerequisite_workflow_ids" — workflow_ids that must be completed before this one becomes eligible):
{required_workflows_json}

completed_workflow_ids_json:
{completed_workflow_ids_json}

outstanding_workflow_ids_json (everything not yet completed, regardless of prereqs):
{outstanding_workflow_ids_json}

next_eligible_workflow_ids_json (THIS is the set you are allowed to suggest — it already excludes completed workflows AND workflows whose prerequisites are not yet satisfied):
{next_eligible_workflow_ids_json}

discovered_features_json:
{discovered_features_json}

recent_activity_text:
{recent_activity_text}
""",
}


# ---------------------------------------------------------------------------
# Onboarding summary — distil a finished session into a short cross-session brief
# ---------------------------------------------------------------------------
#
# Input placeholders (built by
# autoplay_sdk.user_adoption_state.build_onboarding_summary_input):
#   session_number, duration_minutes, journey_state, mastery_level,
#   mastery_rating, reached_onboarding_complete, completion_rate,
#   completed_workflow_ids_json, in_progress_workflow_ids_json,
#   untouched_workflow_ids_json, discovered_features_json
#
# Output: PLAIN TEXT (not JSON) — a 2-3 sentence briefing the agent reads at the
# user's NEXT session start. The SDK never executes this prompt; the integration
# runs it via `acall_llm` and injects the result through `on_session_end`.

ONBOARDING_SUMMARY_PROMPT: dict[str, str] = {
    "name": "onboarding_summary",
    "description": (
        "Distils one finished session (a SessionSnapshot) into a short, "
        "second-person briefing the agent reads at the user's next session "
        "start. Plain-text output, no JSON."
    ),
    "version": "0.1",
    "content": """You write a short continuity brief about a user, for an in-product
assistant that will greet them at the START of their NEXT session.

Summarise what this user did and where they are in their journey so the
assistant can pick up naturally — like a colleague leaving a handover note.

Rules:
- 2-3 sentences, plain text. No markdown, no headings, no bullet points, no emojis.
- Write in the second person about the user ("You finished setting up ...").
- Ground every claim in the data below — never invent activity.
- Note what they completed, what they left in progress, and the single most
  useful thing to help them with next.
- If they have not started much, say so plainly and keep it short.
- Output ONLY the brief — no preamble, no quotes.

---
session_number: {session_number}
duration_minutes: {duration_minutes}
journey_state: {journey_state}
mastery_level: {mastery_level} (rating {mastery_rating}/10)
reached_onboarding_complete: {reached_onboarding_complete}
completion_rate: {completion_rate}

completed_workflow_ids_json:
{completed_workflow_ids_json}

in_progress_workflow_ids_json:
{in_progress_workflow_ids_json}

untouched_workflow_ids_json:
{untouched_workflow_ids_json}

discovered_features_json:
{discovered_features_json}
""",
}
