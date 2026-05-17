"""autoplay-sdk public API surface."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from . import agent_state, async_client, client  # noqa: F401 — required for patch() to resolve submodule attributes

from autoplay_sdk.agent_state import v2 as agent_state_v2
from autoplay_sdk.async_client import AsyncConnectorClient
from autoplay_sdk.buffer import BufferBackend, EventBuffer, RedisEventBuffer
from autoplay_sdk.chat.chatbot import (
    BaseChatbotWriter,
    ConversationEvent,
    ConversationWriter,
    format_chatbot_note_header,
)
from autoplay_sdk.chat.chat_pipeline import AsyncChatPipeline, compose_chat_pipeline
from autoplay_sdk.client import ConnectorClient
from autoplay_sdk.context.context_store import AsyncContextStore, ContextStore
from autoplay_sdk.core.exceptions import (
    SdkBufferFullError,
    SdkConfigError,
    SdkError,
    SdkUpstreamError,
)
from autoplay_sdk.core.metrics import SdkMetricsHook
from autoplay_sdk.core.models import (
    ActionsPayload,
    AnyPayload,
    SlimAction,
    SummaryPayload,
)
from autoplay_sdk.prompts import RAG_SYSTEM_PROMPT, REASONING_PROMPT, RESPONSE_PROMPT
from autoplay_sdk.rag.ingest.ingest import AsyncRagPipeline, RagPipeline
from autoplay_sdk.rag.query import (
    ChatContextAssembly,
    ChatMemoryProvider,
    ChatWatermarkScope,
    InMemoryInboundWatermarkStore,
    InboundWatermarkStore,
    KnowledgeBaseRetriever,
    RagChatProviders,
    RagReplyInputs,
    assemble_rag_chat_context,
    cutoff_for_delta_activity,
    effective_inbound_timestamp,
    format_rag_system_prompt,
    format_reasoning_prompt,
    format_response_prompt,
)
from autoplay_sdk.context.summarizer import (
    DEFAULT_PROMPT,
    AsyncSessionSummarizer,
    SessionSummarizer,
)
from autoplay_sdk.context.agent_context import AsyncAgentContextWriter
from autoplay_sdk.agent_state.v1.states import (
    AgentState,
    AgentStateMachine,
    InvalidSnapshotError,
    InvalidTransitionError,
    SessionMetrics,
    TaskProgress,
)
from autoplay_sdk.webhook_receiver import WebhookReceiver
from autoplay_sdk.context.user_index import SessionRef, UserSessionIndex

__all__ = [
    "ConnectorClient",
    "AsyncConnectorClient",
    "ActionsPayload",
    "SummaryPayload",
    "SlimAction",
    "AnyPayload",
    "EventBuffer",
    "RedisEventBuffer",
    "BufferBackend",
    "ContextStore",
    "AsyncContextStore",
    "RagPipeline",
    "AsyncRagPipeline",
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
    "SessionSummarizer",
    "AsyncSessionSummarizer",
    "DEFAULT_PROMPT",
    "AsyncAgentContextWriter",
    "AgentState",
    "AgentStateMachine",
    "InvalidSnapshotError",
    "InvalidTransitionError",
    "SessionMetrics",
    "TaskProgress",
    "agent_state_v2",
    "ConversationWriter",
    "BaseChatbotWriter",
    "ConversationEvent",
    "format_chatbot_note_header",
    "AsyncChatPipeline",
    "compose_chat_pipeline",
    "UserSessionIndex",
    "SessionRef",
    "WebhookReceiver",
    "SdkMetricsHook",
    "SdkError",
    "SdkConfigError",
    "SdkUpstreamError",
    "SdkBufferFullError",
    "__version__",
]

try:
    __version__ = _pkg_version("autoplay-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
