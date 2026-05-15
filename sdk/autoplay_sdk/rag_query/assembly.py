"""Structured context assembly for query-time RAG (user query + realtime + history + optional KB).

Vendor-neutral defaults — memory/KB backends are injected via :mod:`autoplay_sdk.rag_query.pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatContextAssembly:
    """Structured inputs for versioned chat prompts (any channel: Intercom, in-app, etc.)."""

    recent_activity: str
    kb_records_text: str
    conversation_history_text: str
    user_message: str
    activity_since_last_chat_message: str = ""
    first_question_text: str = ""
    # Source-split fields (populated by :func:`assemble_rag_chat_context` for debugging / dumps)
    session_activity_local: str = ""
    zep_live_activity: str = ""
    zep_conversation_turns: list[dict[str, str]] = field(default_factory=list)
    kb_raw_records: list[dict[str, Any]] = field(default_factory=list)


# Back-compat alias — prefer ChatContextAssembly for new code.
IntercomPromptAssembly = ChatContextAssembly


def format_kb_records_for_prompt(records: list[dict[str, Any]]) -> str:
    """Flatten KB records into a readable block."""
    if not records:
        return ""
    lines: list[str] = ["Knowledge base excerpts:"]
    for i, rec in enumerate(records, start=1):
        title = rec.get("title") or f"Doc {i}"
        body = (rec.get("content") or "").strip()
        if body:
            lines.append(f"--- {title} ---\n{body}")
    return "\n\n".join(lines)


def format_history_for_prompt(
    history: list[dict[str, str]],
    *,
    section_header: str = "Prior conversation:",
) -> str:
    """Format conversation messages oldest-first.

    ``section_header`` can be overridden per channel or memory backend.
    """
    if not history:
        return ""
    lines: list[str] = [section_header]
    for turn in history:
        role = turn.get("role") or "user"
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def build_user_prompt_block(assembly: ChatContextAssembly) -> str:
    """Single user message combining activity, KB, history, and current question.

    Delta activity (since last inbound chat message) is placed **first** so the
    model tailors this reply; broader ``[RECENT PRODUCT ACTIVITY]`` stays for
    full-session grounding when both are present.
    """
    parts: list[str] = []
    if assembly.activity_since_last_chat_message.strip():
        parts.append(
            "[ACTIVITY SINCE YOUR LAST CHAT MESSAGE]\n"
            + assembly.activity_since_last_chat_message.strip()
        )
    if assembly.recent_activity.strip():
        parts.append("[RECENT PRODUCT ACTIVITY]\n" + assembly.recent_activity.strip())
    if assembly.conversation_history_text.strip():
        parts.append(assembly.conversation_history_text.strip())
    if assembly.kb_records_text.strip():
        parts.append(assembly.kb_records_text.strip())
    parts.append("[CURRENT USER MESSAGE]\n" + assembly.user_message.strip())
    return "\n\n".join(parts)


def build_selected_context_for_rag_system_prompt(assembly: ChatContextAssembly) -> str:
    """Product activity + KB only (no chat history — that fills ``conversation_history``).

    Used for ``{selected_context}`` in Adoption Copilot system prompts alongside the separate
    conversation-history placeholder. Omits ``[CURRENT USER MESSAGE]``.
    """
    parts: list[str] = []
    if assembly.activity_since_last_chat_message.strip():
        parts.append(
            "[ACTIVITY SINCE YOUR LAST CHAT MESSAGE]\n"
            + assembly.activity_since_last_chat_message.strip()
        )
    if assembly.recent_activity.strip():
        parts.append("[RECENT PRODUCT ACTIVITY]\n" + assembly.recent_activity.strip())
    if assembly.kb_records_text.strip():
        parts.append(assembly.kb_records_text.strip())
    return "\n\n".join(parts)
