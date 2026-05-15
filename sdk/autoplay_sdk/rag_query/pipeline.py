"""Query-time RAG assembly orchestration — inject realtime activity, history, optional KB.

Core contract: **user query**, **real-time context**, **conversation history** (see package docs).
Optional ``KnowledgeBaseRetriever`` and pluggable ``ChatMemoryProvider`` implement vendor-specific I/O.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from autoplay_sdk.rag_query.assembly import (
    ChatContextAssembly,
    build_user_prompt_block,
    format_history_for_prompt,
    format_kb_records_for_prompt,
)

logger = logging.getLogger(__name__)


def prefer_zep_live_activity_for_rag() -> bool:
    """When True (default), merged ``recent_activity`` uses Zep before Redis context store.

    Zep's ``live-{session_id}`` thread is populated from the same action-derived
    formatted window as the connector context store (see ``run_zep_sync_live_activity``).
    Preferring it makes Intercom RAG use the durable Zep mirror when both are non-empty.
    Set ``RAG_PREFER_ZEP_LIVE_ACTIVITY=0`` to restore legacy behavior (local store first).
    """
    return os.getenv("RAG_PREFER_ZEP_LIVE_ACTIVITY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def skip_redis_context_when_zep_memory() -> bool:
    """When True (default), Redis context-store activity is skipped if Zep returns live text.

    Intercom RAG then uses **Zep** for session-wide activity + conversation history
    (memory provider) and the KB endpoint for chunks — not duplicate Redis formatting.
    If Zep live activity is empty, Redis is still queried as a fallback.
    Set ``RAG_SKIP_REDIS_CONTEXT_WHEN_ZEP=0`` to always call Redis ``session_activity_local``.
    """
    return os.getenv("RAG_SKIP_REDIS_CONTEXT_WHEN_ZEP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


@dataclass(frozen=True)
class RagReplyInputs:
    """Inputs for building the RAG user message block (any chat surface)."""

    product_id: str
    integration_config: dict[str, Any]
    conversation_id: str
    user_message: str
    email: str
    session_id: str | None = None
    activity_since_cutoff: float | None = None


@runtime_checkable
class ChatMemoryProvider(Protocol):
    """Conversation + live activity from any backing store (Zep, Postgres, …)."""

    async def live_activity(self, *, session_id: str, user_id: str) -> str:
        """Recent live product activity snapshot for the session."""
        ...

    async def conversation_turns(
        self,
        *,
        session_id: str,
        conversation_id: str,
        user_id: str,
    ) -> list[dict[str, str]]:
        """Prior turns as ``role`` / ``content`` dicts (oldest-first expected)."""
        ...


@runtime_checkable
class KnowledgeBaseRetriever(Protocol):
    """Optional KB retrieval — customers swap Atlas, Pinecone+RAG, CMS, etc."""

    async def retrieve(
        self,
        *,
        connector_product_id: str,
        kb_product_id: str | None,
        session_id: str,
        user_query: str,
        knowledge_id: str,
        activity_text_for_kb_injection: str,
    ) -> list[dict[str, Any]]: ...


@dataclass
class RagChatProviders:
    """Pluggable sources for :func:`assemble_rag_chat_context`.

    Attributes:
        session_activity_local: Formatted realtime context for ``session_id`` (e.g. Autoplay Redis context store).
        session_activity_since: Optional delta activity since ``activity_since_cutoff`` epoch seconds.
        memory: Optional chat memory + live snapshot; skipped when ``session_id`` is missing (see logs).
        knowledge_base: Optional KB retriever; omit for query + realtime + history only.

    Implementations may raise on I/O failure; exceptions propagate from :func:`assemble_rag_chat_context`.
    """

    session_activity_local: Callable[[str], Awaitable[str]]
    session_activity_since: Callable[[str, float], Awaitable[str]] | None = None
    memory: ChatMemoryProvider | None = None
    knowledge_base: KnowledgeBaseRetriever | None = None


async def assemble_rag_chat_context(
    *,
    product_id: str,
    integration_config: dict[str, Any],
    conversation_id: str,
    user_message: str,
    email: str,
    session_id: str | None,
    activity_since_cutoff: float | None,
    providers: RagChatProviders,
) -> tuple[str, ChatContextAssembly]:
    """Merge activity, optional memory (e.g. Zep), optional KB → user block + assembly.

    **Intercom / connector stack (typical):** With ``zep_api_key`` and ``session_id``,
    the memory provider supplies **live activity** (Zep ``live-{session}`` thread — synced
    from PostHog→actions→formatted context) and **conversation turns** (Zep composite conv
    thread). KB chunks come from ``knowledge_base.retrieve``. Redis context store is optional:
    by default it is **not** queried when Zep already returned live activity (see
    ``skip_redis_context_when_zep_memory`` / ``RAG_SKIP_REDIS_CONTEXT_WHEN_ZEP``).

    Merge order in the user block remains (delta → full activity → history → KB → query)
    where each slice is populated from the providers above.

    Args:
        product_id: Connector / product identifier (included in structured log ``extra`` only).
        integration_config: May include ``kb_product_id``, ``kb_knowledge_id`` for KB retrieval.
        conversation_id: Stable chat thread id.
        user_message: Current user query text (**never** logged by this function).
        email: User identity hint for memory providers.
        session_id: Session key for activity + memory; memory is skipped if absent with a debug line.
        activity_since_cutoff: Epoch seconds for delta activity (with ``session_activity_since``).
        providers: Pluggable session activity, memory, and KB backends.

    Returns:
        ``(user_block, assembly)`` — formatted user message block for the LLM and the structured
        :class:`~autoplay_sdk.rag_query.assembly.ChatContextAssembly` record.

    Raises:
        Any exception raised by ``session_activity_*``, ``memory``, or ``knowledge_base`` awaitables
        (network, auth, validation). Logged once at WARNING with ``exc_info=True`` then re-raised.

    Note:
        Do not log ``user_message`` or full ``assembly`` text in application code when debugging —
        use DEBUG lines from this module (lengths and ids only).
    """
    try:
        user_id = (email or session_id or "anonymous").strip()

        mem = providers.memory
        use_zep_memory = bool(mem and session_id)
        skip_redis_if_zep = use_zep_memory and skip_redis_context_when_zep_memory()

        activity_remote = ""
        history_list: list[dict[str, str]] = []
        if mem and session_id:
            activity_remote = await mem.live_activity(
                session_id=session_id, user_id=user_id
            )
            history_list = await mem.conversation_turns(
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
            )
        elif mem and not session_id:
            logger.debug(
                "rag_query: skipping memory live+history without session_id product=%s conv=%s",
                product_id,
                conversation_id,
            )

        activity_local = ""
        if session_id:
            need_redis_local = True
            if skip_redis_if_zep and (activity_remote or "").strip():
                need_redis_local = False
            if need_redis_local:
                activity_local = await providers.session_activity_local(session_id)

        if prefer_zep_live_activity_for_rag():
            recent_activity = (activity_remote or activity_local or "").strip()
        else:
            recent_activity = (activity_local or activity_remote or "").strip()
        history_text = format_history_for_prompt(history_list)

        first_question_text = ""
        for turn in history_list:
            if (turn.get("role") or "").lower() == "user":
                c = (turn.get("content") or "").strip()
                if c:
                    first_question_text = c
                    break

        activity_since_last = ""
        zep_live_nonempty = bool((activity_remote or "").strip())
        skip_redis_delta = skip_redis_if_zep and zep_live_nonempty
        if (
            session_id
            and activity_since_cutoff is not None
            and providers.session_activity_since is not None
            and not skip_redis_delta
        ):
            activity_since_last = await providers.session_activity_since(
                session_id, activity_since_cutoff
            )

        kb_product_id = (integration_config.get("kb_product_id") or "").strip() or None
        knowledge_id = (integration_config.get("kb_knowledge_id") or "").strip()

        kb_records: list[dict[str, Any]] = []
        if providers.knowledge_base is not None:
            kb_records = await providers.knowledge_base.retrieve(
                connector_product_id=product_id,
                kb_product_id=kb_product_id,
                session_id=session_id or "",
                user_query=user_message,
                knowledge_id=knowledge_id,
                activity_text_for_kb_injection=recent_activity,
            )
        kb_text = format_kb_records_for_prompt(kb_records)

        assembly = ChatContextAssembly(
            recent_activity=recent_activity,
            kb_records_text=kb_text,
            conversation_history_text=history_text,
            user_message=user_message,
            activity_since_last_chat_message=activity_since_last,
            first_question_text=first_question_text or user_message,
            session_activity_local=(activity_local or "").strip(),
            zep_live_activity=(activity_remote or "").strip(),
            zep_conversation_turns=list(history_list),
            kb_raw_records=list(kb_records),
        )
        user_block = build_user_prompt_block(assembly)
    except Exception:
        logger.warning(
            "rag_query: assemble_rag_chat_context failed product=%s conv=%s",
            product_id,
            conversation_id,
            exc_info=True,
            extra={
                "product_id": product_id,
                "conversation_id": conversation_id,
                "session_id": session_id,
                "event_type": "rag_query_assemble_failed",
            },
        )
        raise

    logger.debug(
        "rag_query: assemble_rag_chat_context ok product=%s conv=%s",
        product_id,
        conversation_id,
        extra={
            "product_id": product_id,
            "conversation_id": conversation_id,
            "session_id": session_id,
            "event_type": "rag_query_assemble_ok",
            "has_memory": bool(providers.memory and session_id),
            "has_kb": providers.knowledge_base is not None,
            "has_delta_activity": bool(
                session_id
                and activity_since_cutoff is not None
                and providers.session_activity_since is not None
            ),
            "user_block_chars": len(user_block),
            "recent_activity_chars": len(recent_activity),
            "history_chars": len(history_text),
            "kb_chars": len(kb_text),
            "activity_since_chars": len(activity_since_last),
        },
    )
    return user_block, assembly


async def assemble_rag_chat_context_from_inputs(
    inputs: RagReplyInputs,
    *,
    providers: RagChatProviders,
) -> tuple[str, ChatContextAssembly]:
    """Same as :func:`assemble_rag_chat_context` using a frozen input bundle."""
    return await assemble_rag_chat_context(
        product_id=inputs.product_id,
        integration_config=inputs.integration_config,
        conversation_id=inputs.conversation_id,
        user_message=inputs.user_message,
        email=inputs.email,
        session_id=inputs.session_id,
        activity_since_cutoff=inputs.activity_since_cutoff,
        providers=providers,
    )
