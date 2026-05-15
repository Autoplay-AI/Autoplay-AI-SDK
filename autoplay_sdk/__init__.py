"""autoplay-sdk — real-time event streaming client for Autoplay connectors.

Receives structured UI actions and LLM session summaries from the Autoplay
event connector via SSE (Server-Sent Events) or webhook POSTs, then routes
them into your RAG pipeline, vector store, or agent context.

Components
----------
Clients (choose one):
    ConnectorClient       — sync SSE client; separate reader + worker threads;
                            safe for blocking callbacks.
    AsyncConnectorClient  — async SSE client; per-session semaphore isolation;
                            use ``async def`` callbacks for any I/O.
    WebhookReceiver       — push mode; HMAC-SHA256 verification + typed dispatch.

Typed models:
    ActionsPayload        — batch of UI actions from a session.
    SummaryPayload        — LLM-generated session summary.

Pipeline components (mix and match):
    EventBuffer           — in-memory pull buffer; thread-safe; dev/testing.
    RedisEventBuffer      — Redis-backed sliding-window buffer; async; production.
    SessionSummarizer     — sync rolling LLM summarizer; compact context window.
    AsyncSessionSummarizer— async version; per-session workers; ordering guarantee.
    ContextStore          — sync store; call ``enrich(session_id, query)`` at query time.
    AsyncContextStore     — async write side; sync ``enrich()`` safe from any coroutine.
    RagPipeline           — sync embed + upsert wired to client callbacks (ingestion path).
    AsyncRagPipeline      — async embed + upsert; awaits your embedding and vector store.
    rag_query subpackage   — query-time RAG: assemble user query + realtime context +
                            conversation history (+ optional KB) for chat LLM prompts.
    AsyncAgentContextWriter — push raw actions; overwrite with LLM summary.
    agent_states           — session FSM: ``AgentState`` / ``AgentStateMachine`` for
                            reactive vs proactive vs guidance execution vs conservative;
                            ``to_snapshot`` / ``from_snapshot`` for Redis multi-worker.

    Chatbot destination building blocks:
    ConversationWriter    — typed Protocol for all writer destinations.
    BaseChatbotWriter     — base class: pre-link buffer, post-link debounce,
                            note formatting, session-link webhook topic gate +
                            ``extract_conversation_event``.  Subclass and implement
                            ``_post_note`` / ``_redact_part``; set
                            ``SESSION_LINK_WEBHOOK_TOPICS`` and
                            ``_parse_session_link_webhook_payload`` for webhooks.
    ConversationEvent     — normalised DTO from chatbot link webhooks.
    format_chatbot_note_header — standard ``session_id:`` / ``timestamp:`` header
                            for action and summary notes (use in custom writers).

Observability:
    SdkMetricsHook        — optional Prometheus/Datadog/OTEL-style counters
                            (``metrics=`` on clients, summarizer, Redis buffer).
    Logging               — all SDK loggers live under the ``autoplay_sdk.*``
                            namespace; the package does not call
                            ``logging.basicConfig``. Configure levels from your
                            app (see README § Logging and ``docs/sdk/logging.mdx``).

See the project README on PyPI or GitHub for the full architecture diagram,
quickstart examples, sync-vs-async decision guide, and performance/locking
reference: https://github.com/Autoplay-AI/Autoplay-AI-SDK/tree/main/.#readme
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from . import agent_state_v2
from autoplay_sdk.async_client import AsyncConnectorClient
from autoplay_sdk.buffer import BufferBackend, EventBuffer, RedisEventBuffer
from autoplay_sdk.chatbot import (
    BaseChatbotWriter,
    ConversationEvent,
    ConversationWriter,
    format_chatbot_note_header,
)
from autoplay_sdk.chat_pipeline import AsyncChatPipeline, compose_chat_pipeline
from autoplay_sdk.client import ConnectorClient
from autoplay_sdk.context_store import AsyncContextStore, ContextStore
from autoplay_sdk.exceptions import (
    SdkBufferFullError,
    SdkConfigError,
    SdkError,
    SdkUpstreamError,
)
from autoplay_sdk.metrics import SdkMetricsHook
from autoplay_sdk.models import ActionsPayload, AnyPayload, SlimAction, SummaryPayload
from autoplay_sdk.prompts import RAG_SYSTEM_PROMPT, REASONING_PROMPT, RESPONSE_PROMPT
from autoplay_sdk.rag import AsyncRagPipeline, RagPipeline
from autoplay_sdk.rag_query import (
    ChatContextAssembly,
    ChatMemoryProvider,
    ChatWatermarkScope,
    KnowledgeBaseRetriever,
    RagChatProviders,
    RagReplyInputs,
    assemble_rag_chat_context,
    cutoff_for_delta_activity,
    effective_inbound_timestamp,
    format_rag_system_prompt,
    format_reasoning_prompt,
    format_response_prompt,
    InMemoryInboundWatermarkStore,
    InboundWatermarkStore,
)
from autoplay_sdk.summarizer import (
    DEFAULT_PROMPT,
    AsyncSessionSummarizer,
    SessionSummarizer,
)
from autoplay_sdk.agent_context import AsyncAgentContextWriter
from autoplay_sdk.agent_states import (
    AgentState,
    AgentStateMachine,
    InvalidSnapshotError,
    InvalidTransitionError,
    SessionMetrics,
    TaskProgress,
)
from autoplay_sdk.webhook_receiver import WebhookReceiver
from autoplay_sdk.user_index import SessionRef, UserSessionIndex

__all__ = [
    # Clients
    "ConnectorClient",
    "AsyncConnectorClient",
    # Typed models
    "ActionsPayload",
    "SummaryPayload",
    "SlimAction",
    "AnyPayload",
    # Buffer
    "EventBuffer",
    "RedisEventBuffer",
    "BufferBackend",
    # Context store (query-time RAG enrichment)
    "ContextStore",
    "AsyncContextStore",
    # RAG pipeline (ingestion — upsert flow)
    "RagPipeline",
    "AsyncRagPipeline",
    # Query-time RAG (chat context assembly + Adoption Copilot prompts)
    "ChatContextAssembly",
    "ChatMemoryProvider",
    "KnowledgeBaseRetriever",
    "RagChatProviders",
    "RagReplyInputs",
    "assemble_rag_chat_context",
    "ChatWatermarkScope",
    "cutoff_for_delta_activity",
    "effective_inbound_timestamp",
    "InMemoryInboundWatermarkStore",
    "InboundWatermarkStore",
    "format_rag_system_prompt",
    "format_reasoning_prompt",
    "format_response_prompt",
    "RAG_SYSTEM_PROMPT",
    "REASONING_PROMPT",
    "RESPONSE_PROMPT",
    # Summarizer
    "SessionSummarizer",
    "AsyncSessionSummarizer",
    "DEFAULT_PROMPT",
    # Agent context writer (push model — real-time events → agent destination)
    "AsyncAgentContextWriter",
    # Agent session states (copilot FSM — snapshots for Redis / workers)
    "AgentState",
    "AgentStateMachine",
    "InvalidSnapshotError",
    "InvalidTransitionError",
    "SessionMetrics",
    "TaskProgress",
    "agent_state_v2",
    # Chatbot destination building blocks
    "ConversationWriter",
    "BaseChatbotWriter",
    "ConversationEvent",
    "format_chatbot_note_header",
    "AsyncChatPipeline",
    "compose_chat_pipeline",
    "UserSessionIndex",
    "SessionRef",
    # Push webhook receiver
    "WebhookReceiver",
    # Observability
    "SdkMetricsHook",
    # Exceptions
    "SdkError",
    "SdkConfigError",
    "SdkUpstreamError",
    "SdkBufferFullError",
    # Version
    "__version__",
]
try:
    __version__ = _pkg_version("autoplay-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
