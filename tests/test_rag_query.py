"""Tests for autoplay_sdk.rag_query — assembly, formatters, assemble_rag_chat_context."""

from __future__ import annotations

import logging

import pytest

from autoplay_sdk.prompts.adoption_copilot import RAG_SYSTEM_PROMPT, REASONING_PROMPT
from autoplay_sdk.rag_query import (
    ChatContextAssembly,
    RagChatProviders,
    assemble_rag_chat_context,
    build_user_prompt_block,
    format_history_for_prompt,
    format_rag_system_prompt,
    format_reasoning_prompt,
)


class _Mem:
    async def live_activity(self, *, session_id: str, user_id: str) -> str:
        return "live_z"

    async def conversation_turns(
        self,
        *,
        session_id: str,
        conversation_id: str,
        user_id: str,
    ) -> list[dict[str, str]]:
        return [{"role": "user", "content": "first q"}]


class _Kb:
    async def retrieve(
        self,
        *,
        connector_product_id: str,
        kb_product_id: str | None,
        session_id: str,
        user_query: str,
        knowledge_id: str,
        activity_text_for_kb_injection: str,
    ) -> list[dict]:
        return [{"title": "Doc", "content": "body"}]


class _EmptyZepLiveMem:
    async def live_activity(self, *, session_id: str, user_id: str) -> str:
        return ""

    async def conversation_turns(
        self,
        *,
        session_id: str,
        conversation_id: str,
        user_id: str,
    ) -> list[dict[str, str]]:
        return [{"role": "user", "content": "prior"}]


def test_format_history_default_is_vendor_neutral() -> None:
    text = format_history_for_prompt([{"role": "user", "content": "hi"}])
    assert text.startswith("Prior conversation:")


def test_build_user_prompt_block_delta_first() -> None:
    asm = ChatContextAssembly(
        recent_activity="broad",
        kb_records_text="",
        conversation_history_text="",
        user_message="q",
        activity_since_last_chat_message="delta line",
    )
    block = build_user_prompt_block(asm)
    assert block.index("[ACTIVITY SINCE YOUR LAST CHAT MESSAGE]") < block.index(
        "[RECENT PRODUCT ACTIVITY]"
    )


def test_format_rag_system_prompt_fills_placeholders() -> None:
    asm = ChatContextAssembly(
        recent_activity="act",
        kb_records_text="kb",
        conversation_history_text="Prior conversation:\nuser: hi",
        user_message="q",
        activity_since_last_chat_message="since",
        first_question_text="hi",
    )
    text = format_rag_system_prompt(
        template_content=RAG_SYSTEM_PROMPT["content"],
        assembly=asm,
        user_question="q",
    )
    assert "Adoption Copilot" in text
    assert "Prior conversation" in text
    assert "[ACTIVITY SINCE YOUR LAST CHAT MESSAGE]" in text


def test_format_reasoning_prompt_preserves_json_examples() -> None:
    filled = format_reasoning_prompt(
        template_content=REASONING_PROMPT["content"],
        user_question="What did I do?",
        first_question="What did I do?",
        conversation_history="(none)",
        ui_actions_preview="Recent: click",
    )
    assert '"intent"' in filled
    assert "What did I do?" in filled


@pytest.mark.asyncio
async def test_assemble_rag_chat_context_with_mock_providers() -> None:
    async def local_act(sid: str) -> str:
        return "local_act" if sid == "s1" else ""

    async def since_act(sid: str, cutoff: float) -> str:
        return "since_only"

    providers = RagChatProviders(
        session_activity_local=local_act,
        session_activity_since=since_act,
        memory=_Mem(),
        knowledge_base=_Kb(),
    )
    user_block, asm = await assemble_rag_chat_context(
        product_id="p1",
        integration_config={"kb_knowledge_id": "kid"},
        conversation_id="c1",
        user_message="hello",
        email="e@test.com",
        session_id="s1",
        activity_since_cutoff=100.0,
        providers=providers,
    )
    assert asm.user_message == "hello"
    # RAG_SKIP_REDIS_CONTEXT_WHEN_ZEP=1: Redis local not fetched when Zep returns live text.
    assert asm.session_activity_local == ""
    assert asm.zep_live_activity == "live_z"
    assert asm.recent_activity == "live_z"
    assert asm.zep_conversation_turns == [{"role": "user", "content": "first q"}]
    assert len(asm.kb_raw_records) == 1
    assert asm.kb_raw_records[0].get("title") == "Doc"
    # Redis delta skipped when Zep live activity is non-empty (Intercom = Zep + KB).
    assert asm.activity_since_last_chat_message == ""
    assert "Knowledge base excerpts" in asm.kb_records_text
    assert "[CURRENT USER MESSAGE]" in user_block
    assert "hello" in user_block


@pytest.mark.asyncio
async def test_assemble_rag_chat_context_failure_logs_warning_then_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(_sid: str) -> str:
        raise RuntimeError("provider down")

    providers = RagChatProviders(session_activity_local=boom)
    with caplog.at_level(logging.WARNING, logger="autoplay_sdk.rag_query.pipeline"):
        with pytest.raises(RuntimeError, match="provider down"):
            await assemble_rag_chat_context(
                product_id="p",
                integration_config={},
                conversation_id="c",
                user_message="hi",
                email="e",
                session_id="s",
                activity_since_cutoff=None,
                providers=providers,
            )
    assert any("assemble_rag_chat_context failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_assemble_rag_chat_context_local_first_when_zep_preference_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PREFER_ZEP_LIVE_ACTIVITY", "0")
    monkeypatch.setenv("RAG_SKIP_REDIS_CONTEXT_WHEN_ZEP", "0")

    async def local_act(sid: str) -> str:
        return "local_act" if sid == "s1" else ""

    async def since_act(sid: str, cutoff: float) -> str:
        return "since_only"

    providers = RagChatProviders(
        session_activity_local=local_act,
        session_activity_since=since_act,
        memory=_Mem(),
        knowledge_base=_Kb(),
    )
    _, asm = await assemble_rag_chat_context(
        product_id="p1",
        integration_config={"kb_knowledge_id": "kid"},
        conversation_id="c1",
        user_message="hello",
        email="e@test.com",
        session_id="s1",
        activity_since_cutoff=100.0,
        providers=providers,
    )
    assert asm.recent_activity == "local_act"
    assert asm.activity_since_last_chat_message == "since_only"


@pytest.mark.asyncio
async def test_redis_local_used_when_zep_live_empty() -> None:
    async def local_act(sid: str) -> str:
        return "from_redis" if sid == "s1" else ""

    providers = RagChatProviders(
        session_activity_local=local_act,
        session_activity_since=None,
        memory=_EmptyZepLiveMem(),
        knowledge_base=None,
    )
    _, asm = await assemble_rag_chat_context(
        product_id="p1",
        integration_config={},
        conversation_id="c1",
        user_message="hi",
        email="e@test.com",
        session_id="s1",
        activity_since_cutoff=None,
        providers=providers,
    )
    assert asm.session_activity_local == "from_redis"
    assert asm.zep_live_activity == ""
    assert asm.recent_activity == "from_redis"


@pytest.mark.asyncio
async def test_assemble_rag_chat_context_minimal_no_memory_no_kb() -> None:
    async def local_only(sid: str) -> str:
        return "ctx"

    providers = RagChatProviders(
        session_activity_local=local_only,
        session_activity_since=None,
        memory=None,
        knowledge_base=None,
    )
    _, asm = await assemble_rag_chat_context(
        product_id="p",
        integration_config={},
        conversation_id="c",
        user_message="hi",
        email="x@y.z",
        session_id="sess",
        activity_since_cutoff=None,
        providers=providers,
    )
    assert asm.recent_activity == "ctx"
    assert asm.kb_records_text == ""
    assert asm.conversation_history_text == ""
