"""Contracts for loading :class:`~autoplay_sdk.models.ActionsPayload` batches for proactive context.

Hosts implement :class:`RecentActionsPayloadSource` in the connector or app layer (e.g. in-memory
store, Zep). The SDK stays free of connector imports.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from autoplay_sdk.models import ActionsPayload
from autoplay_sdk.proactive_triggers.scope import ScopePolicy
from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S,
    DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS,
    ProactiveTriggerContext,
)


@runtime_checkable
class RecentActionsPayloadSource(Protocol):
    """Load recent action batches for a session (connector supplies concrete implementations)."""

    def load_payloads(
        self, *, product_id: str, session_id: str
    ) -> Sequence[ActionsPayload]:
        """Return payloads in chronological order (typically mirroring the context store)."""
        ...


def build_proactive_context_from_payloads(
    payloads: Sequence[ActionsPayload],
    *,
    lookback_seconds: float | None = DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S,
    max_actions: int | None = DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS,
    now: float | None = None,
    session_id: str = "",
    conversation_id: str = "",
    product_id: str = "",
    action_count: int = 0,
    latest_summary_text: str = "",
    prior_session_summaries: tuple[str, ...] = (),
    context_extra: dict[str, Any] | None = None,
    scope_policy: ScopePolicy = ScopePolicy.STRICT,
    require_conversation: bool = False,
) -> ProactiveTriggerContext:
    """Thin wrapper around :meth:`ProactiveTriggerContext.from_actions_payloads` for one call site."""
    return ProactiveTriggerContext.from_actions_payloads(
        payloads,
        lookback_seconds=lookback_seconds,
        max_actions=max_actions,
        now=now,
        session_id=session_id,
        conversation_id=conversation_id,
        product_id=product_id,
        action_count=action_count,
        latest_summary_text=latest_summary_text,
        prior_session_summaries=prior_session_summaries,
        context_extra=context_extra,
        scope_policy=scope_policy,
        require_conversation=require_conversation,
    )
