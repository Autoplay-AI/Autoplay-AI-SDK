"""Query-time RAG — assemble user query, realtime context, conversation history, optional KB.

This is **not** :mod:`autoplay_sdk.rag` (ingestion embed/upsert). Use ``rag_query`` for
chat reply context blocks and Adoption Copilot prompt formatters.

**Observability:** log records from assembly live under the ``autoplay_sdk.rag_query.*`` namespace
(see :mod:`autoplay_sdk.rag_query.pipeline`). The SDK never logs full user messages or prompts —
only correlation ids and character counts at DEBUG. Configure logging in your app; see the SDK
**Logging** doc (``docs/sdk/logging.mdx``) for lazy ``%`` formatting and safe ``extra`` fields.
"""

from autoplay_sdk.rag_query.assembly import (
    ChatContextAssembly,
    IntercomPromptAssembly,
    build_selected_context_for_rag_system_prompt,
    build_user_prompt_block,
    format_history_for_prompt,
    format_kb_records_for_prompt,
)
from autoplay_sdk.rag_query.formatters import (
    format_rag_system_prompt,
    format_reasoning_prompt,
    format_response_prompt,
    previews_for_reasoning_from_assembly,
)
from autoplay_sdk.rag_query.pipeline import (
    ChatMemoryProvider,
    KnowledgeBaseRetriever,
    RagChatProviders,
    RagReplyInputs,
    assemble_rag_chat_context,
    assemble_rag_chat_context_from_inputs,
)
from autoplay_sdk.rag_query.watermark import (
    ChatWatermarkScope,
    InMemoryInboundWatermarkStore,
    InboundWatermarkStore,
    cutoff_for_delta_activity,
    effective_inbound_timestamp,
)

__all__ = [
    "ChatContextAssembly",
    "ChatMemoryProvider",
    "IntercomPromptAssembly",
    "KnowledgeBaseRetriever",
    "RagChatProviders",
    "RagReplyInputs",
    "assemble_rag_chat_context",
    "assemble_rag_chat_context_from_inputs",
    "ChatWatermarkScope",
    "cutoff_for_delta_activity",
    "effective_inbound_timestamp",
    "InboundWatermarkStore",
    "InMemoryInboundWatermarkStore",
    "build_selected_context_for_rag_system_prompt",
    "build_user_prompt_block",
    "format_history_for_prompt",
    "format_kb_records_for_prompt",
    "format_rag_system_prompt",
    "format_reasoning_prompt",
    "format_response_prompt",
    "previews_for_reasoning_from_assembly",
]
