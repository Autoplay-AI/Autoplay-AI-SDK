"""Scope validation and logging for proactive trigger contexts (product / session / conversation)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("autoplay_sdk.proactive_triggers.scope")

# Structured log event name — align with connector ``log_trace`` search.
SCOPE_INVALID_EVENT = "proactive_trigger_scope_invalid"


class ScopePolicy(Enum):
    """How strictly :meth:`ProactiveTriggerContext.from_slim_actions` /
    :meth:`~ProactiveTriggerContext.from_actions_payloads` validate identifiers."""

    STRICT = "strict"
    """Require non-empty ``product_id`` and ``session_id`` (after strip)."""

    LENIENT = "lenient"
    """Skip identifier validation (legacy / tests / connector paths with optional session)."""


@dataclass(frozen=True)
class ProactiveScope:
    """Explicit isolation boundary for proactive detection (typed cue for integrators).

    **Baseline:** ``product_id`` + ``session_id``. Add ``conversation_id`` when the user
    is linked to a chat thread (Intercom, etc.).
    """

    product_id: str
    session_id: str
    conversation_id: str = ""

    def has_chat_surface(self) -> bool:
        return bool((self.conversation_id or "").strip())


def _trim(s: str | None) -> str:
    return (s or "").strip()


def scope_presence_flags(
    *,
    product_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, bool]:
    """Boolean presence flags for structured logs (no raw identifiers)."""
    return {
        "product_id_set": bool(_trim(product_id)),
        "session_id_set": bool(_trim(session_id)),
        "conversation_id_set": bool(_trim(conversation_id)),
    }


def log_scope_violation(
    *,
    scope_error: str,
    extra: dict[str, bool | str] | None = None,
    level: int = logging.WARNING,
) -> None:
    """Emit one structured log line when scope validation fails (no PII)."""
    payload: dict[str, bool | str] = {
        "event": SCOPE_INVALID_EVENT,
        "scope_error": scope_error,
    }
    if extra:
        payload.update(extra)
    logger.log(level, "proactive trigger scope invalid", extra=payload)


def validate_proactive_scope_fields(
    *,
    product_id: str,
    session_id: str,
    conversation_id: str = "",
    require_conversation: bool = False,
    policy: ScopePolicy = ScopePolicy.STRICT,
) -> None:
    """Raise :exc:`ValueError` and log when ``policy`` is :attr:`ScopePolicy.STRICT` and fields are missing."""
    if policy is not ScopePolicy.STRICT:
        return

    pid, sid, cid = _trim(product_id), _trim(session_id), _trim(conversation_id)
    flags = scope_presence_flags(
        product_id=product_id, session_id=session_id, conversation_id=conversation_id
    )

    if not pid:
        log_scope_violation(scope_error="missing_product_id", extra=flags)
        raise ValueError(
            "ProactiveTriggerContext requires non-empty product_id (ScopePolicy.STRICT)"
        )
    if not sid:
        log_scope_violation(scope_error="missing_session_id", extra=flags)
        raise ValueError(
            "ProactiveTriggerContext requires non-empty session_id (ScopePolicy.STRICT)"
        )
    if require_conversation and not cid:
        log_scope_violation(scope_error="missing_conversation_id", extra=flags)
        raise ValueError(
            "ProactiveTriggerContext requires non-empty conversation_id when require_conversation=True"
        )
