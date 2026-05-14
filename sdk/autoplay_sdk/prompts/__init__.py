"""Versioned default prompts for Adoption Copilot query-time RAG."""

from autoplay_sdk.prompts.adoption_copilot import (
    RAG_SYSTEM_PROMPT,
    REASONING_PROMPT,
    RESPONSE_PROMPT,
)
from autoplay_sdk.prompts.intercom_readability import (
    INTERCOM_READABILITY_RULES,
    READABILITY_RULES_FINGERPRINT,
    RULES_VERSION,
)

__all__ = [
    "INTERCOM_READABILITY_RULES",
    "READABILITY_RULES_FINGERPRINT",
    "RAG_SYSTEM_PROMPT",
    "REASONING_PROMPT",
    "RESPONSE_PROMPT",
    "RULES_VERSION",
]
