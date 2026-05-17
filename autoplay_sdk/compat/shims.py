"""Central shim registry for one-release import compatibility."""

from __future__ import annotations

import warnings
from importlib import import_module
from typing import Any

SHIM_MAP: list[dict[str, str]] = [
    {"old_module": "autoplay_sdk.serve", "new_module": "autoplay_sdk.api"},
    {
        "old_module": "autoplay_sdk.serve.fastapi",
        "new_module": "autoplay_sdk.api.fastapi",
    },
    {
        "old_module": "autoplay_sdk.agent_states",
        "new_module": "autoplay_sdk.agent_state.v1.states",
    },
    {
        "old_module": "autoplay_sdk.agent_states.state_machine",
        "new_module": "autoplay_sdk.agent_state.v1.state_machine",
    },
    {
        "old_module": "autoplay_sdk.agent_states.types",
        "new_module": "autoplay_sdk.agent_state.v1.types",
    },
    {
        "old_module": "autoplay_sdk.agent_states.proactive_idle_expiry",
        "new_module": "autoplay_sdk.proactive.state.idle_expiry",
    },
    {
        "old_module": "autoplay_sdk.agent_state_v2",
        "new_module": "autoplay_sdk.agent_state.v2.states",
    },
    {
        "old_module": "autoplay_sdk.agent_state_v2.session_state",
        "new_module": "autoplay_sdk.agent_state.v2.session_state",
    },
    {
        "old_module": "autoplay_sdk.agent_state_v2.types",
        "new_module": "autoplay_sdk.agent_state.v2.types",
    },
    {"old_module": "autoplay_sdk.rag_query", "new_module": "autoplay_sdk.rag.query"},
    {
        "old_module": "autoplay_sdk.rag_query.assembly",
        "new_module": "autoplay_sdk.rag.query.assembly",
    },
    {
        "old_module": "autoplay_sdk.rag_query.formatters",
        "new_module": "autoplay_sdk.rag.query.formatters",
    },
    {
        "old_module": "autoplay_sdk.rag_query.pipeline",
        "new_module": "autoplay_sdk.rag.query.pipeline",
    },
    {
        "old_module": "autoplay_sdk.rag_query.watermark",
        "new_module": "autoplay_sdk.rag.query.watermark",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience",
        "new_module": "autoplay_sdk.proactive.resilience.resilience",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience.circuit",
        "new_module": "autoplay_sdk.proactive.resilience.circuit",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience.config",
        "new_module": "autoplay_sdk.proactive.resilience.config",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience.keys",
        "new_module": "autoplay_sdk.proactive.resilience.keys",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience.outcomes",
        "new_module": "autoplay_sdk.proactive.resilience.outcomes",
    },
    {
        "old_module": "autoplay_sdk.proactive_resilience.protocol",
        "new_module": "autoplay_sdk.proactive.resilience.protocol",
    },
    {"old_module": "autoplay_sdk.chatbot", "new_module": "autoplay_sdk.chat.chatbot"},
    {
        "old_module": "autoplay_sdk.chat_pipeline",
        "new_module": "autoplay_sdk.chat.chat_pipeline",
    },
    {
        "old_module": "autoplay_sdk.context_store",
        "new_module": "autoplay_sdk.context.context_store",
    },
    {
        "old_module": "autoplay_sdk.agent_context",
        "new_module": "autoplay_sdk.context.agent_context",
    },
    {
        "old_module": "autoplay_sdk.user_index",
        "new_module": "autoplay_sdk.context.user_index",
    },
    {
        "old_module": "autoplay_sdk.summarizer",
        "new_module": "autoplay_sdk.context.summarizer",
    },
    {"old_module": "autoplay_sdk.models", "new_module": "autoplay_sdk.core.models"},
    {
        "old_module": "autoplay_sdk.exceptions",
        "new_module": "autoplay_sdk.core.exceptions",
    },
    {"old_module": "autoplay_sdk.metrics", "new_module": "autoplay_sdk.core.metrics"},
    {
        "old_module": "autoplay_sdk.onboarding",
        "new_module": "autoplay_sdk.admin.onboarding",
    },
    {
        "old_module": "autoplay_sdk.proactive_idle_expiry",
        "new_module": "autoplay_sdk.proactive.state.idle_expiry",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers",
        "new_module": "autoplay_sdk.proactive.triggers",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.builtin_catalog",
        "new_module": "autoplay_sdk.proactive.triggers.builtin_catalog",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.context_source",
        "new_module": "autoplay_sdk.proactive.triggers.context_source",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.defaults",
        "new_module": "autoplay_sdk.proactive.triggers.defaults",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.entity",
        "new_module": "autoplay_sdk.proactive.triggers.entity",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.judge",
        "new_module": "autoplay_sdk.proactive.triggers.judge",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.pending_tour_offer",
        "new_module": "autoplay_sdk.proactive.triggers.pending_tour_offer",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.predicate_trigger",
        "new_module": "autoplay_sdk.proactive.triggers.predicate_trigger",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.proactive_intercom_config",
        "new_module": "autoplay_sdk.proactive.triggers.proactive_intercom_config",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.quick_reply_match",
        "new_module": "autoplay_sdk.proactive.triggers.quick_reply_match",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.registry",
        "new_module": "autoplay_sdk.proactive.triggers.registry",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.scope",
        "new_module": "autoplay_sdk.proactive.triggers.scope",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.section_activity",
        "new_module": "autoplay_sdk.proactive.triggers.section_activity",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.tour_registry",
        "new_module": "autoplay_sdk.proactive.triggers.tour_registry",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.trigger_config",
        "new_module": "autoplay_sdk.proactive.triggers.trigger_config",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.triggers",
        "new_module": "autoplay_sdk.proactive.triggers.triggers",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.triggers.canonical_ping_pong",
        "new_module": "autoplay_sdk.proactive.triggers.triggers.canonical_ping_pong",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.triggers.scoped_canonical_ping_pong",
        "new_module": "autoplay_sdk.proactive.triggers.triggers.scoped_canonical_ping_pong",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.triggers.section_playbook",
        "new_module": "autoplay_sdk.proactive.triggers.triggers.section_playbook",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.triggers.user_page_dwell",
        "new_module": "autoplay_sdk.proactive.triggers.triggers.user_page_dwell",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.types",
        "new_module": "autoplay_sdk.proactive.triggers.types",
    },
    {
        "old_module": "autoplay_sdk.proactive_triggers.url_scope",
        "new_module": "autoplay_sdk.proactive.triggers.url_scope",
    },
]


def reexport_with_warning(old_module: str, new_module: str) -> Any:
    warnings.warn(
        f"`{old_module}` has moved to `{new_module}`. Update your imports before 1.0.0, when the old path will be removed.",
        DeprecationWarning,
        stacklevel=2,
    )
    return import_module(new_module)
