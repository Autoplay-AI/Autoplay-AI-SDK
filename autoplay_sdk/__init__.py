"""autoplay-sdk public API surface."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from autoplay_sdk.agent_state import v2 as agent_state_v2
from autoplay_sdk.async_client import AsyncConnectorClient
from autoplay_sdk.buffer import BufferBackend, EventBuffer, RedisEventBuffer
from autoplay_sdk.chat.chatbot import (
    AutoplayChatbotManager,
    BaseChatbotWriter,
    ConversationLink,
    ConversationEventType,
    ConversationWebhookEvent,
    ConversationWriter,
    InMemoryConversationLinkStore,
    InMemorySessionStateStore,
    RedisSessionStateStore,
    format_chatbot_note_header,
    link_conversation,
    resolve_linked_conversation_id,
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
from autoplay_sdk.webhook_receiver import WebhookReceiver
from autoplay_sdk.context.user_index import SessionRef, UserSessionIndex
from autoplay_sdk import user_adoption_state
from autoplay_sdk.user_adoption_state import (
    JourneyState,
    MasteryLevel,
    UserAdoptionState,
    WorkflowStatus,
)
from autoplay_sdk.providers import (
    ActivityProvider,
    PostHogProvider,
    ProviderRegistrationBody,
)

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
    "agent_state_v2",
    "ConversationWriter",
    "BaseChatbotWriter",
    "ConversationLink",
    "ConversationEventType",
    "ConversationWebhookEvent",
    "AutoplayChatbotManager",
    "InMemoryConversationLinkStore",
    "InMemorySessionStateStore",
    "RedisSessionStateStore",
    "format_chatbot_note_header",
    "link_conversation",
    "resolve_linked_conversation_id",
    "AsyncChatPipeline",
    "compose_chat_pipeline",
    "UserSessionIndex",
    "SessionRef",
    "user_adoption_state",
    "UserAdoptionState",
    "JourneyState",
    "MasteryLevel",
    "WorkflowStatus",
    "WebhookReceiver",
    "SdkMetricsHook",
    "SdkError",
    "SdkConfigError",
    "SdkUpstreamError",
    "SdkBufferFullError",
    "ActivityProvider",
    "PostHogProvider",
    "ProviderRegistrationBody",
    "__version__",
]

try:
    __version__ = _pkg_version("autoplay-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0+local"


def __getattr__(name: str) -> object:
    if name == "ConversationEvent":
        import warnings

        warnings.warn(
            "ConversationEvent is deprecated and will be removed in the next major version. "
            "Update your import: from autoplay_sdk import ConversationEventType",
            DeprecationWarning,
            stacklevel=2,
        )
        return ConversationEventType
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
