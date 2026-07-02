"""Tests for :class:`autoplay_sdk.prompts.PromptVoice`.

The dataclass is the contract every integration uses to inject its own
domain copy into the onboarding welcome + follow-up prompts. These tests
lock the parsing contract (per-field fallback to defaults, ignore
unknown keys, tolerate missing config entirely) so an integration that
overrides only one field — or none — gets predictable behaviour.

Also exercises the prompt-fill round-trip: a PromptVoice built from a
realistic config dict must produce a string with every placeholder
substituted (no stray ``{voice_anchor_phrase}`` left in the body) when
threaded through the welcome / follow-up prompt templates with the rest
of the runner's input slots.
"""

from __future__ import annotations

import pytest

from autoplay_sdk.prompts import (
    ONBOARDING_FOLLOWUP_PROMPT,
    ONBOARDING_WELCOME_PROMPT,
    PromptVoice,
)


class TestFromConfigDefaults:
    """``from_config`` falls back to defaults when no override is given."""

    def test_missing_config_returns_defaults(self) -> None:
        voice = PromptVoice.from_config(None)
        assert voice == PromptVoice()

    def test_empty_dict_returns_defaults(self) -> None:
        voice = PromptVoice.from_config({})
        assert voice == PromptVoice()

    def test_non_dict_returns_defaults(self) -> None:
        # JSON arrives untrusted from product config; integers / lists at
        # the top level shouldn't blow up — silently degrade to defaults.
        for raw in (123, "string", [], False):
            assert PromptVoice.from_config(raw) == PromptVoice()  # type: ignore[arg-type]


class TestFromConfigPerFieldOverride:
    """Each field is independently overridable; un-set fields keep the default."""

    def test_only_anchor_overridden(self) -> None:
        voice = PromptVoice.from_config(
            {"voice_anchor_phrase": "ship the perfect demo on day one"}
        )
        assert voice.voice_anchor_phrase == "ship the perfect demo on day one"
        # Every other field stays at the SDK default.
        defaults = PromptVoice()
        assert voice.workflow_example_a_name == defaults.workflow_example_a_name
        assert voice.path_to_language_examples == defaults.path_to_language_examples
        assert voice.closer_fallback_text == defaults.closer_fallback_text

    def test_only_workflow_examples_overridden(self) -> None:
        voice = PromptVoice.from_config(
            {
                "workflow_example_a_name": "Connect your CRM",
                "workflow_example_a_id": "flow-connect-crm",
            }
        )
        assert voice.workflow_example_a_name == "Connect your CRM"
        assert voice.workflow_example_a_id == "flow-connect-crm"
        # B-side untouched.
        assert voice.workflow_example_b_name == PromptVoice().workflow_example_b_name

    def test_full_override(self) -> None:
        raw = {
            "voice_anchor_phrase": "x",
            "workflow_example_a_name": "A",
            "workflow_example_a_id": "a",
            "workflow_example_b_name": "B",
            "workflow_example_b_id": "b",
            "path_to_language_examples": [["/p", "page p"]],
            "previous_session_callback_example": "back?",
            "why_it_mattered_example": "matters",
            "closer_fallback_text": "done",
        }
        voice = PromptVoice.from_config(raw)
        assert voice.voice_anchor_phrase == "x"
        assert voice.workflow_example_a_id == "a"
        assert voice.path_to_language_examples == (("/p", "page p"),)
        assert voice.closer_fallback_text == "done"

    def test_unknown_keys_are_silently_ignored(self) -> None:
        # Defensive against typos / future fields that older deployed
        # connectors don't know about — wouldn't want one rogue key to
        # tank the entire voice config.
        voice = PromptVoice.from_config(
            {
                "voice_anchor_phrase": "kept",
                "totally_made_up_field": "ignored",
            }
        )
        assert voice.voice_anchor_phrase == "kept"

    def test_null_field_falls_back_to_default(self) -> None:
        # JSON null is a legitimate way for a customer to say "no override
        # here, please use the SDK default" — don't render it literally
        # into the prompt as "None".
        voice = PromptVoice.from_config({"voice_anchor_phrase": None})
        assert voice.voice_anchor_phrase == PromptVoice().voice_anchor_phrase


class TestPathExamplesParsing:
    """``path_to_language_examples`` accepts a list of ``[path, phrase]`` pairs."""

    def test_valid_pairs_parsed_into_tuples(self) -> None:
        voice = PromptVoice.from_config(
            {
                "path_to_language_examples": [
                    ["/dashboard", "the dashboard"],
                    ["/orders/:id", "an order"],
                ]
            }
        )
        assert voice.path_to_language_examples == (
            ("/dashboard", "the dashboard"),
            ("/orders/:id", "an order"),
        )

    def test_malformed_entries_dropped(self) -> None:
        # Bad entries (wrong arity, non-strings) are dropped; valid
        # entries SURVIVE rather than the whole list being thrown out.
        voice = PromptVoice.from_config(
            {
                "path_to_language_examples": [
                    ["/dashboard", "the dashboard"],
                    ["only-one-element"],
                    [1, 2],
                    ["/orders", "your orders"],
                ]
            }
        )
        assert voice.path_to_language_examples == (
            ("/dashboard", "the dashboard"),
            ("/orders", "your orders"),
        )

    def test_empty_list_falls_back_to_defaults(self) -> None:
        # An empty list would render an empty bullet list inside the
        # prompt body, which would confuse the LLM more than the
        # defaults would. Fall back rather than ship an empty section.
        voice = PromptVoice.from_config({"path_to_language_examples": []})
        assert (
            voice.path_to_language_examples == PromptVoice().path_to_language_examples
        )

    def test_non_list_falls_back_to_defaults(self) -> None:
        voice = PromptVoice.from_config({"path_to_language_examples": "not a list"})
        assert (
            voice.path_to_language_examples == PromptVoice().path_to_language_examples
        )

    def test_render_path_examples_format(self) -> None:
        voice = PromptVoice(
            path_to_language_examples=(
                ("/dashboard", "the dashboard"),
                ("/orders/:id", "an order"),
            )
        )
        rendered = voice.render_path_examples()
        assert '"/dashboard" → "the dashboard"' in rendered
        assert '"/orders/:id" → "an order"' in rendered

    def test_render_handles_empty(self) -> None:
        voice = PromptVoice(path_to_language_examples=())
        # Should produce a placeholder rather than an empty string so
        # the LLM sees the section, not a confusing blank gap.
        assert voice.render_path_examples().strip() != ""


class TestPromptFillRoundTrip:
    """A voice built from realistic config fills both prompt templates cleanly."""

    @pytest.fixture
    def leytongo_voice(self) -> PromptVoice:
        # Realistic shape — matches the prompt_voice block we ship for
        # the LeytonGo product in products.json.
        return PromptVoice.from_config(
            {
                "voice_anchor_phrase": (
                    "get maximum value out of the product as quickly as possible"
                ),
                "workflow_example_a_name": "Create your first CAE product",
                "workflow_example_a_id": "flow-admin-create-product",
                "workflow_example_b_name": "Configure your columns",
                "workflow_example_b_id": "flow-admin-columns-management",
                "path_to_language_examples": [
                    ["/caes/abc-123/leads", "your leads"],
                    ["/dashboard", "the dashboard"],
                ],
                "previous_session_callback_example": (
                    "Last time we worked on configuring your columns — "
                    "want to pick up there?"
                ),
                "why_it_mattered_example": (
                    "It's the column setup everything else hangs off of."
                ),
                "closer_fallback_text": "Boom — onboarding done.",
            }
        )

    # The full set of input slots each prompt declares. Lifted into a
    # module-level list so the "no unfilled placeholder" check below can
    # iterate; also serves as living documentation of the contract.
    _WELCOME_SLOTS = (
        "role",
        "role_label",
        "seconds_on_app",
        "distinct_features_seen",
        "proactive_support_count",
        "required_workflows_json",
        "completed_workflow_ids_json",
        "next_eligible_workflow_ids_json",
        "discovered_features_json",
        "recent_activity_text",
        "previous_session_summary",
        "voice_anchor_phrase",
        "workflow_example_a_name",
        "workflow_example_a_id",
        "workflow_example_b_name",
        "workflow_example_b_id",
        "path_to_language_examples_text",
        "previous_session_callback_example",
    )
    _FOLLOWUP_SLOTS = (
        "role",
        "event",
        "abandoned_at_step",
        "just_completed_workflow_json",
        "required_workflows_json",
        "completed_workflow_ids_json",
        "outstanding_workflow_ids_json",
        "next_eligible_workflow_ids_json",
        "discovered_features_json",
        "recent_activity_text",
        "why_it_mattered_example",
    )

    def test_welcome_prompt_fills_with_no_stray_placeholders(
        self, leytongo_voice: PromptVoice
    ) -> None:
        # Mirror the input dict the welcome runner builds — every slot
        # the prompt template declares must be supplied or .format()
        # raises KeyError. This test exists specifically to catch the
        # case where someone adds a {placeholder} to the prompt body
        # without wiring it through the runner.
        prompt_text = ONBOARDING_WELCOME_PROMPT["content"].format(
            role="consultant",
            role_label="Consultant",
            seconds_on_app=0,
            distinct_features_seen=0,
            proactive_support_count=0,
            required_workflows_json="[]",
            completed_workflow_ids_json="[]",
            next_eligible_workflow_ids_json="[]",
            discovered_features_json="[]",
            recent_activity_text="",
            previous_session_summary="",
            voice_anchor_phrase=leytongo_voice.voice_anchor_phrase,
            workflow_example_a_name=leytongo_voice.workflow_example_a_name,
            workflow_example_a_id=leytongo_voice.workflow_example_a_id,
            workflow_example_b_name=leytongo_voice.workflow_example_b_name,
            workflow_example_b_id=leytongo_voice.workflow_example_b_id,
            path_to_language_examples_text=leytongo_voice.render_path_examples(),
            previous_session_callback_example=(
                leytongo_voice.previous_session_callback_example
            ),
        )
        # No `{slot_name}` literal survived the fill — that would mean
        # we declared a slot we forgot to supply. Checking by slot name
        # (rather than any `{`) keeps the JSON-shape docstrings in the
        # prompt body — e.g. `{workflow_id, status, ...}` — out of the
        # false-positive set.
        for slot in self._WELCOME_SLOTS:
            assert "{" + slot + "}" not in prompt_text, (
                f"stray placeholder {{{slot}}} found in welcome prompt — "
                "added a {name} to the body without wiring it through "
                "PromptVoice + runner?"
            )
        # The injected anchor sentence MUST appear verbatim — that's the
        # whole point of PromptVoice.
        assert leytongo_voice.voice_anchor_phrase in prompt_text
        assert leytongo_voice.workflow_example_a_name in prompt_text
        # Path exemplars rendered as a bullet list inside the prompt body.
        assert '"/caes/abc-123/leads"' in prompt_text
        # No LeytonGo copy left BAKED into the SDK template body —
        # `ONBOARDING_WELCOME_PROMPT["content"]` itself must be domain-
        # agnostic, the customer copy comes from the input only.
        assert "CAE product" not in ONBOARDING_WELCOME_PROMPT["content"]
        assert "Configure your columns" not in ONBOARDING_WELCOME_PROMPT["content"]
        assert "/caes/" not in ONBOARDING_WELCOME_PROMPT["content"]
        assert (
            "get maximum value out of the product"
            not in ONBOARDING_WELCOME_PROMPT["content"]
        )

    def test_followup_prompt_fills_with_no_stray_placeholders(
        self, leytongo_voice: PromptVoice
    ) -> None:
        prompt_text = ONBOARDING_FOLLOWUP_PROMPT["content"].format(
            role="consultant",
            event="completed",
            abandoned_at_step="null",
            just_completed_workflow_json="null",
            required_workflows_json="[]",
            completed_workflow_ids_json="[]",
            outstanding_workflow_ids_json="[]",
            next_eligible_workflow_ids_json="[]",
            discovered_features_json="[]",
            recent_activity_text="",
            why_it_mattered_example=leytongo_voice.why_it_mattered_example,
        )
        for slot in self._FOLLOWUP_SLOTS:
            assert "{" + slot + "}" not in prompt_text, (
                f"stray placeholder {{{slot}}} found in followup prompt — "
                "added a {name} to the body without wiring it through "
                "PromptVoice + runner?"
            )
        assert leytongo_voice.why_it_mattered_example in prompt_text
        # No LeytonGo copy baked into the followup SDK template either.
        assert "column setup" not in ONBOARDING_FOLLOWUP_PROMPT["content"]
        assert "CAE" not in ONBOARDING_FOLLOWUP_PROMPT["content"]
