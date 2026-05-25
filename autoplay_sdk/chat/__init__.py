from autoplay_sdk.chat.chat_pipeline import AsyncChatPipeline, compose_chat_pipeline
from autoplay_sdk.chat.chatbot import (
    BaseChatbotWriter,
    ConversationLink,
    ConversationLinkStore,
    ConversationEventType,
    ConversationWebhookEvent,
    ConversationWriter,
    InMemoryConversationLinkStore,
    format_chatbot_note_header,
    link_conversation,
    resolve_linked_conversation_id,
)

__all__ = [
    "AsyncChatPipeline",
    "BaseChatbotWriter",
    "ConversationLink",
    "ConversationLinkStore",
    "ConversationEventType",
    "ConversationWebhookEvent",
    "ConversationWriter",
    "InMemoryConversationLinkStore",
    "compose_chat_pipeline",
    "format_chatbot_note_header",
    "link_conversation",
    "resolve_linked_conversation_id",
]


def __getattr__(name: str) -> object:
    if name == "ConversationEvent":
        import warnings

        warnings.warn(
            "ConversationEvent is deprecated and will be removed in the next major version. "
            "Update your import: from autoplay_sdk.chat import ConversationEventType",
            DeprecationWarning,
            stacklevel=2,
        )
        return ConversationEventType
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
