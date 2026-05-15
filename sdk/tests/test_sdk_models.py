"""Tests for autoplay_sdk.models — SlimAction, ActionsPayload, SummaryPayload."""

from __future__ import annotations

import pytest

from autoplay_sdk.models import ActionsPayload, SlimAction, SummaryPayload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slim_dict(**overrides: object) -> dict:
    base: dict = {
        "title": "Clicked Export",
        "description": "Clicked Export CSV button",
        "canonical_url": "/dashboard",
    }
    return {**base, **overrides}


def _actions_dict(**overrides: object) -> dict:
    base: dict = {
        "type": "actions",
        "product_id": "prod1",
        "session_id": "sess1",
        "user_id": "u1",
        "email": "user@example.com",
        "actions": [_slim_dict()],
        "count": 1,
        "forwarded_at": 9999.0,
    }
    return {**base, **overrides}


def _summary_dict(**overrides: object) -> dict:
    base: dict = {
        "type": "summary",
        "product_id": "prod1",
        "session_id": "sess1",
        "summary": "User navigated to Dashboard and exported a CSV.",
        "replaces": 7,
        "forwarded_at": 9999.0,
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# SlimAction
# ---------------------------------------------------------------------------


class TestSlimAction:
    def test_from_dict_populates_all_fields(self):
        a = SlimAction.from_dict(_slim_dict())
        assert a.title == "Clicked Export"
        assert a.description == "Clicked Export CSV button"
        assert a.canonical_url == "/dashboard"

    def test_from_dict_missing_fields_default_to_empty_string(self):
        a = SlimAction.from_dict({})
        assert a.title == ""
        assert a.description == ""
        assert a.canonical_url == ""

    def test_from_dict_identity_fields_optional(self):
        a = SlimAction.from_dict(
            _slim_dict(
                session_id="ps_1",
                user_id="distinct_abc",
                email="u@example.com",
            )
        )
        assert a.session_id == "ps_1"
        assert a.user_id == "distinct_abc"
        assert a.email == "u@example.com"

    def test_from_dict_identity_defaults_to_none(self):
        a = SlimAction.from_dict(_slim_dict())
        assert a.session_id is None
        assert a.user_id is None
        assert a.email is None
        assert a.conversation_id is None

    def test_from_dict_conversation_id_optional(self):
        a = SlimAction.from_dict(_slim_dict(conversation_id="ic_conv_1"))
        assert a.conversation_id == "ic_conv_1"

    def test_to_text_contains_description_and_url(self):
        a = SlimAction(title="T", description="Did something", canonical_url="/path")
        text = a.to_text()
        assert "Did something" in text
        assert "/path" in text

    def test_to_text_does_not_include_title(self):
        a = SlimAction(title="IGNORED_TITLE", description="desc", canonical_url="/url")
        assert "IGNORED_TITLE" not in a.to_text()

    def test_to_text_format_uses_em_dash_separator(self):
        a = SlimAction(
            title="t", description="desc", canonical_url="/url", index=0, type="click"
        )
        assert a.to_text() == "[0] click: desc — /url"


# ---------------------------------------------------------------------------
# ActionsPayload
# ---------------------------------------------------------------------------


class TestActionsPayload:
    def test_from_dict_populates_all_fields(self):
        p = ActionsPayload.from_dict(_actions_dict())
        assert p.product_id == "prod1"
        assert p.session_id == "sess1"
        assert p.user_id == "u1"
        assert p.email == "user@example.com"
        assert p.count == 1
        assert p.forwarded_at == 9999.0
        assert len(p.actions) == 1
        assert isinstance(p.actions[0], SlimAction)
        assert p.conversation_id is None

    def test_from_dict_includes_conversation_id_when_present(self):
        p = ActionsPayload.from_dict(_actions_dict(conversation_id="ic_99"))
        assert p.conversation_id == "ic_99"

    def test_from_dict_optional_fields_default_to_none(self):
        p = ActionsPayload.from_dict({"actions": [], "count": 0, "forwarded_at": 0.0})
        assert p.session_id is None
        assert p.user_id is None
        assert p.email is None

    def test_from_dict_missing_required_fields_use_safe_defaults(self):
        p = ActionsPayload.from_dict({})
        assert p.product_id == ""
        assert p.count == 0
        assert p.forwarded_at == 0.0
        assert p.actions == []

    def test_actions_are_parsed_as_slim_action_instances(self):
        d = _actions_dict(actions=[_slim_dict(), _slim_dict(title="Second")])
        p = ActionsPayload.from_dict(d)
        assert len(p.actions) == 2
        assert all(isinstance(a, SlimAction) for a in p.actions)

    def test_to_text_first_line_contains_session_id_and_count(self):
        actions = [_slim_dict(), _slim_dict(title="B"), _slim_dict(title="C")]
        p = ActionsPayload.from_dict(
            _actions_dict(session_id="sess42", actions=actions, count=3)
        )
        first_line = p.to_text().splitlines()[0]
        assert "sess42" in first_line
        assert "3" in first_line

    def test_to_text_uses_unknown_for_none_session_id(self):
        p = ActionsPayload.from_dict(_actions_dict(session_id=None))
        assert "unknown" in p.to_text().splitlines()[0]

    def test_to_text_enumerates_actions_in_order(self):
        d = _actions_dict(
            actions=[
                _slim_dict(description="First", canonical_url="/a"),
                _slim_dict(description="Second", canonical_url="/b"),
            ],
            count=2,
        )
        p = ActionsPayload.from_dict(d)
        lines = p.to_text().splitlines()
        assert "First" in lines[1]
        assert "Second" in lines[2]

    def test_to_text_includes_action_description_and_url(self):
        d = _actions_dict(
            actions=[_slim_dict(description="Exported CSV", canonical_url="/exports")],
            count=1,
        )
        text = ActionsPayload.from_dict(d).to_text()
        assert "Exported CSV" in text
        assert "/exports" in text

    def test_to_text_returns_string(self):
        assert isinstance(ActionsPayload.from_dict(_actions_dict()).to_text(), str)


# ---------------------------------------------------------------------------
# ActionsPayload.merge()
# ---------------------------------------------------------------------------


class TestActionsPayloadMerge:
    def _make_payload(
        self,
        session_id: str = "sess1",
        n_actions: int = 1,
        user_id: str | None = None,
        email: str | None = None,
        forwarded_at: float = 1.0,
        conversation_id: str | None = None,
    ) -> ActionsPayload:
        actions = [
            SlimAction(
                title=f"T{i}",
                description=f"Did thing {i}",
                canonical_url=f"/page/{i}",
                index=i,
            )
            for i in range(n_actions)
        ]
        return ActionsPayload(
            product_id="prod1",
            session_id=session_id,
            user_id=user_id,
            email=email,
            actions=actions,
            count=n_actions,
            forwarded_at=forwarded_at,
            conversation_id=conversation_id,
        )

    def test_empty_list_raises_value_error(self):
        with pytest.raises(ValueError, match="at least one"):
            ActionsPayload.merge([])

    def test_single_payload_returns_equivalent(self):
        p = self._make_payload(n_actions=2, forwarded_at=5.0)
        merged = ActionsPayload.merge([p])
        assert merged.product_id == p.product_id
        assert merged.session_id == p.session_id
        assert merged.forwarded_at == 5.0
        assert len(merged.actions) == 2
        assert merged.count == 2

    def test_two_payloads_actions_are_concatenated(self):
        p1 = self._make_payload(n_actions=2, forwarded_at=1.0)
        p2 = self._make_payload(n_actions=3, forwarded_at=2.0)
        merged = ActionsPayload.merge([p1, p2])
        assert len(merged.actions) == 5
        assert merged.count == 5

    def test_actions_are_reindexed_sequentially(self):
        p1 = self._make_payload(n_actions=2)
        p2 = self._make_payload(n_actions=2)
        merged = ActionsPayload.merge([p1, p2])
        assert [a.index for a in merged.actions] == [0, 1, 2, 3]

    def test_forwarded_at_is_max_of_inputs(self):
        p1 = self._make_payload(forwarded_at=1.0)
        p2 = self._make_payload(forwarded_at=9.5)
        p3 = self._make_payload(forwarded_at=3.0)
        merged = ActionsPayload.merge([p1, p2, p3])
        assert merged.forwarded_at == 9.5

    def test_user_id_resolved_from_first_nonnone(self):
        p1 = self._make_payload(user_id=None)
        p2 = self._make_payload(user_id="uid_42")
        p3 = self._make_payload(user_id="uid_99")
        merged = ActionsPayload.merge([p1, p2, p3])
        assert merged.user_id == "uid_42"

    def test_email_resolved_from_first_nonnone(self):
        p1 = self._make_payload(email=None)
        p2 = self._make_payload(email="alice@example.com")
        merged = ActionsPayload.merge([p1, p2])
        assert merged.email == "alice@example.com"

    def test_conversation_id_resolved_from_first_nonnone(self):
        p1 = self._make_payload(conversation_id=None)
        p2 = self._make_payload(conversation_id="ic_link")
        merged = ActionsPayload.merge([p1, p2])
        assert merged.conversation_id == "ic_link"

    def test_user_id_and_email_none_when_all_none(self):
        p1 = self._make_payload(user_id=None, email=None)
        p2 = self._make_payload(user_id=None, email=None)
        merged = ActionsPayload.merge([p1, p2])
        assert merged.user_id is None
        assert merged.email is None

    def test_product_id_and_session_id_from_first_payload(self):
        p1 = self._make_payload(session_id="sess_A")
        p2 = self._make_payload(session_id="sess_B")
        merged = ActionsPayload.merge([p1, p2])
        assert merged.session_id == "sess_A"
        assert merged.product_id == "prod1"

    def test_original_payloads_are_not_mutated(self):
        p1 = self._make_payload(n_actions=2)
        original_indices = [a.index for a in p1.actions]
        ActionsPayload.merge([p1, self._make_payload(n_actions=2)])
        assert [a.index for a in p1.actions] == original_indices


# ---------------------------------------------------------------------------
# SummaryPayload
# ---------------------------------------------------------------------------


class TestSummaryPayload:
    def test_from_dict_populates_all_fields(self):
        p = SummaryPayload.from_dict(_summary_dict())
        assert p.product_id == "prod1"
        assert p.session_id == "sess1"
        assert p.summary == "User navigated to Dashboard and exported a CSV."
        assert p.replaces == 7
        assert p.forwarded_at == 9999.0

    def test_from_dict_session_id_can_be_none(self):
        p = SummaryPayload.from_dict(
            {"summary": "s", "replaces": 0, "forwarded_at": 0.0}
        )
        assert p.session_id is None

    def test_from_dict_missing_fields_use_safe_defaults(self):
        p = SummaryPayload.from_dict({})
        assert p.product_id == ""
        assert p.summary == ""
        assert p.replaces == 0
        assert p.forwarded_at == 0.0

    def test_to_text_returns_the_summary_string_verbatim(self):
        p = SummaryPayload.from_dict(_summary_dict(summary="User visited settings."))
        assert p.to_text() == "User visited settings."

    def test_to_text_returns_empty_string_when_summary_is_missing(self):
        assert SummaryPayload.from_dict({}).to_text() == ""

    def test_to_text_api_is_symmetric_with_actions_payload(self):
        """Both payload types expose .to_text() so callers never need to branch."""
        ap = ActionsPayload.from_dict(_actions_dict())
        sp = SummaryPayload.from_dict(_summary_dict())
        assert isinstance(ap.to_text(), str)
        assert isinstance(sp.to_text(), str)
