"""Fill RAG / reasoning / response prompt templates (no LLM side effects)."""

from __future__ import annotations

from typing import Any

from autoplay_sdk.rag_query.assembly import (
    ChatContextAssembly,
    build_selected_context_for_rag_system_prompt,
)


def format_rag_system_prompt(
    *,
    template_content: str,
    assembly: ChatContextAssembly,
    user_question: str,
    reasoning_intent: str = "Single-pass RAG; routing call not used.",
    reasoning_sources: str = "(none)",
    reasoning_explanation: str = "Use all provided context blocks below.",
    selected_task_context: str = "",
) -> str:
    """Populate Adoption Copilot ``RAG_SYSTEM_PROMPT`` ``content`` string.

    ``selected_context`` is built from activity + KB only; conversation history
    fills its own placeholder.
    """
    fq = (assembly.first_question_text or "").strip() or user_question.strip()
    conv = (assembly.conversation_history_text or "").strip() or "(none)"
    sel = build_selected_context_for_rag_system_prompt(assembly).strip() or "(none)"
    task_ctx = (selected_task_context or "").strip()
    return template_content.format(
        user_question=user_question.strip(),
        first_question=fq,
        selected_task_context=task_ctx,
        conversation_history=conv,
        reasoning_intent=reasoning_intent,
        reasoning_sources=reasoning_sources,
        reasoning_explanation=reasoning_explanation,
        selected_context=sel,
    )


def format_reasoning_prompt(
    *,
    template_content: str,
    user_question: str,
    first_question: str,
    conversation_history: str,
    ui_actions_preview: str = "(none)",
    kb_articles_preview: str = "(none)",
    past_session_preview: str = "(none)",
    task_analysis_preview: str = "(none)",
    matched_actions_preview: str = "(none)",
    selected_task_preview: str = "(none)",
) -> str:
    """Populate ``REASONING_PROMPT`` ``content`` string."""
    return template_content.format(
        user_question=user_question.strip(),
        first_question=(first_question or user_question).strip(),
        conversation_history=conversation_history.strip() or "(none)",
        ui_actions_preview=ui_actions_preview,
        kb_articles_preview=kb_articles_preview,
        past_session_preview=past_session_preview,
        task_analysis_preview=task_analysis_preview,
        matched_actions_preview=matched_actions_preview,
        selected_task_preview=selected_task_preview,
    )


def format_response_prompt(
    *,
    template_content: str,
    company_overview: str,
    terra_catalog: str,
    ai_input_summary: str,
    past_session_context: str,
    user_question: str,
) -> str:
    """Populate ``RESPONSE_PROMPT`` ``content`` string."""
    return template_content.format(
        company_overview=company_overview or "(none)",
        terra_catalog=terra_catalog or "(none)",
        ai_input_summary=ai_input_summary or "(none)",
        past_session_context=past_session_context.strip(),
        user_question=user_question.strip(),
    )


def previews_for_reasoning_from_assembly(
    *,
    assembly: ChatContextAssembly,
    ui_actions_preview: str | None = None,
    kb_records: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Default Reasoning prompt previews from an assembled RAG context."""
    ui = (
        ui_actions_preview
        if ui_actions_preview is not None
        else _ui_actions_preview_from_assembly(assembly)
    )
    kb_txt = "(none)"
    if kb_records:
        lines = []
        for i, rec in enumerate(kb_records[:5], start=1):
            t = (rec.get("title") or f"Doc {i}")[:200]
            lines.append(f"- {t}")
        kb_txt = "\n".join(lines)
    elif assembly.kb_records_text.strip():
        kb_txt = assembly.kb_records_text.strip()[:8000]
    return {
        "ui_actions_preview": ui,
        "kb_articles_preview": kb_txt,
        "past_session_preview": "(none)",
        "task_analysis_preview": "(none)",
        "matched_actions_preview": "(none)",
        "selected_task_preview": "(none)",
    }


def _ui_actions_preview_from_assembly(assembly: ChatContextAssembly) -> str:
    """Rough ui_actions preview from activity strings when no split formatter."""
    parts: list[str] = []
    if assembly.activity_since_last_chat_message.strip():
        parts.append(
            "Most recent actions (since last chat message):\n"
            + assembly.activity_since_last_chat_message.strip()
        )
    if assembly.recent_activity.strip():
        parts.append(
            "Earlier in session / broader activity:\n"
            + assembly.recent_activity.strip()
        )
    return "\n\n".join(parts) if parts else "(none)"
