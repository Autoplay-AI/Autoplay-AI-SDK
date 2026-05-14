"""Inbound message watermarks for delta activity (since last user chat message).

Use with :func:`autoplay_sdk.rag_query.pipeline.assemble_rag_chat_context` by passing
``activity_since_cutoff=cutoff_for_delta_activity(await store.get_previous_inbound_at(scope))``.

Typical lifecycle: on each inbound user message, read previous timestamp → assemble RAG with
that value as cutoff → produce reply → :meth:`InboundWatermarkStore.set_last_inbound_at`
with **this** message's time (after delivery succeeds).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatWatermarkScope:
    """Neutral identity for a chat thread (map from Intercom, Slack, in-app, etc.).

    Attributes:
        conversation_id: Stable thread id for the conversation.
        product_id: Optional product / connector id (Autoplay uses this with Intercom).
        tenant_id: Optional customer tenant for multi-tenant apps.
    """

    conversation_id: str
    product_id: str | None = None
    tenant_id: str | None = None


def cutoff_for_delta_activity(previous_inbound_at: float | None) -> float | None:
    """Return the cutoff epoch seconds for ``assemble_rag_chat_context(..., activity_since_cutoff=...)``.

    Pass the value returned by :meth:`InboundWatermarkStore.get_previous_inbound_at` —
    i.e. the **previous** inbound user message time, **not** the current message time.

    ``None`` means no delta block (first message or unknown history).
    """
    return previous_inbound_at


def effective_inbound_timestamp(
    message_created_at: float | None,
    *,
    fallback: float | None = None,
) -> float:
    """Unix epoch seconds for this inbound message (for persisting after a successful reply).

    **Validation:** values are coerced with :class:`float` only. Negative or nonsensical epochs
    from upstream APIs are **not** rejected — ensure the channel provides sensible seconds since epoch.

    If ``message_created_at`` is ``None``, uses ``fallback`` or :func:`time.time`.
    """
    if message_created_at is not None:
        return float(message_created_at)
    if fallback is not None:
        return float(fallback)
    return time.time()


@runtime_checkable
class InboundWatermarkStore(Protocol):
    """Persist last successful inbound user message time per thread."""

    async def get_previous_inbound_at(
        self,
        scope: ChatWatermarkScope,
    ) -> float | None:
        """Unix seconds of the **previous** inbound user message, or ``None`` if unknown."""
        ...

    async def set_last_inbound_at(self, scope: ChatWatermarkScope, at: float) -> None:
        """Record that an inbound user message at ``at`` was processed (cursor for next turn)."""
        ...


class InMemoryInboundWatermarkStore:
    """Process-local watermark store (dev, tests, single-instance demos).

    Not suitable for multi-worker production — use Redis/SQL via a custom
    :class:`InboundWatermarkStore` implementation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple[str | None, str | None, str], float] = {}

    def _key(self, scope: ChatWatermarkScope) -> tuple[str | None, str | None, str]:
        return (scope.tenant_id, scope.product_id, scope.conversation_id)

    async def get_previous_inbound_at(
        self,
        scope: ChatWatermarkScope,
    ) -> float | None:
        with self._lock:
            return self._data.get(self._key(scope))

    async def set_last_inbound_at(self, scope: ChatWatermarkScope, at: float) -> None:
        with self._lock:
            self._data[self._key(scope)] = float(at)
