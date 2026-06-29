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
from autoplay_sdk.prompts.user_adoption import (
    ADOPTION_STATE_JUDGE_PROMPT,
    ONBOARDING_FOLLOWUP_PROMPT,
    ONBOARDING_SUMMARY_PROMPT,
    ONBOARDING_WELCOME_PROMPT,
    TOUR_MATCH_PROMPT,
    PromptVoice,
)

__all__ = [
    "INTERCOM_READABILITY_RULES",
    "READABILITY_RULES_FINGERPRINT",
    "RAG_SYSTEM_PROMPT",
    "REASONING_PROMPT",
    "RESPONSE_PROMPT",
    "RULES_VERSION",
    "ADOPTION_STATE_JUDGE_PROMPT",
    "TOUR_MATCH_PROMPT",
    "ONBOARDING_WELCOME_PROMPT",
    "ONBOARDING_FOLLOWUP_PROMPT",
    "ONBOARDING_SUMMARY_PROMPT",
    "PromptVoice",
]
