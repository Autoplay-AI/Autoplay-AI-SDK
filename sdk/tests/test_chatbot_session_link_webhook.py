"""BaseChatbotWriter session-link webhook class methods."""

from __future__ import annotations

from typing import ClassVar

from autoplay_sdk.chatbot import BaseChatbotWriter, ConversationEvent


def test_base_extract_returns_none_when_no_topics_configured() -> None:
    payload = {"topic": "anything", "data": {}}
    assert BaseChatbotWriter.extract_conversation_event(payload) is None


class _DummyLinkWriter(BaseChatbotWriter):
    SESSION_LINK_WEBHOOK_TOPICS: ClassVar[tuple[str, ...]] = ("vendor.created",)

    @classmethod
    def _parse_session_link_webhook_payload(
        cls, payload: dict
    ) -> ConversationEvent | None:
        return ConversationEvent(
            conversation_id=str(payload.get("cid", "")),
            external_id="u1",
            email="",
        )


def test_subclass_extract_delegates_to_parse() -> None:
    ev = _DummyLinkWriter.extract_conversation_event(
        {"topic": "vendor.created", "cid": "c99"}
    )
    assert ev is not None
    assert ev.conversation_id == "c99"
    assert ev.external_id == "u1"


def test_subclass_extract_wrong_topic_returns_none() -> None:
    assert (
        _DummyLinkWriter.extract_conversation_event({"topic": "other", "cid": "c99"})
        is None
    )
