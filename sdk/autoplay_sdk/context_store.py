"""autoplay_sdk.context_store — Query-time session context for RAG enrichment.

Accumulates real-time user actions and LLM-generated session summaries per
session so you can enrich a user's query with their current in-app context
before sending it to a vector database.

The primary entry point is ``enrich(session_id, query)`` — it returns a single
string that combines the session context with the user's query, ready to embed
and use as the retrieval query::

    enriched = context_store.enrich(session_id, user_message)
    results  = vector_db.query(embed(enriched))

Sync usage::

    import openai
    from autoplay_sdk import ConnectorClient
    from autoplay_sdk.summarizer import SessionSummarizer
    from autoplay_sdk.context_store import ContextStore

    summarizer    = SessionSummarizer(llm=my_llm, threshold=10)
    context_store = ContextStore(
        summarizer=summarizer,
        lookback_seconds=300,  # only last 5 min of actions by default
        max_actions=20,
    )

    client = ConnectorClient(url=URL, token=TOKEN)
    client.on_actions(context_store.add)
    client.run_in_background()

    # In your chatbot handler
    def chat(session_id: str, query: str) -> str:
        enriched = context_store.enrich(session_id, query)
        results  = vector_db.query(embed(enriched))
        return llm(results, query)

Async usage::

    from autoplay_sdk import AsyncConnectorClient
    from autoplay_sdk.summarizer import AsyncSessionSummarizer
    from autoplay_sdk.context_store import AsyncContextStore

    summarizer    = AsyncSessionSummarizer(llm=my_async_llm, threshold=10)
    context_store = AsyncContextStore(summarizer=summarizer)

    client = AsyncConnectorClient(url=URL, token=TOKEN)
    client.on_actions(context_store.add)
    task = client.run_in_background()

    async def chat(session_id: str, query: str) -> str:
        enriched = context_store.enrich(session_id, query)
        results  = await vector_db.query(await embed(enriched))
        return await llm(results, query)

Configuration — all options can be set as defaults at construction time and
overridden per ``enrich()`` / ``get()`` call::

    # Summaries only — no raw actions
    context_store.enrich(session_id, query, include_actions=False)

    # Actions only — skip the summary
    context_store.enrich(session_id, query, include_summary=False)

    # Only actions from the last 60 seconds
    context_store.enrich(session_id, query, lookback_seconds=60)

    # At most the 5 most recent actions
    context_store.enrich(session_id, query, max_actions=5)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from typing import Any

from autoplay_sdk.models import ActionsPayload
from autoplay_sdk.summarizer import _format_actions

logger = logging.getLogger(__name__)

_SENTINEL = object()  # used to detect "not provided" kwargs


def actions_bucket_id(product_id: str | None, session_id: str | None) -> str:
    """Internal key for :attr:`_ContextStoreBase._actions` when ``product_id`` is set.

    **Legacy:** if ``product_id`` is missing or empty, the bucket is ``session_id``
    only (backward compatible). Otherwise ``"{product_id}\\x1f{session_id}"`` so
    concurrent products never share the same PostHog session string by accident.
    """
    sid = (session_id or "unknown").strip()
    pid = (product_id or "").strip()
    if pid:
        return f"{pid}\x1f{sid}"
    return sid


def _resolve(kwarg: Any, default: Any) -> Any:
    """Return ``kwarg`` if it was explicitly provided, else ``default``."""
    return default if kwarg is _SENTINEL else kwarg


# ---------------------------------------------------------------------------
# Shared base — in-memory state + read-path (no I/O; sync and async safe)
# ---------------------------------------------------------------------------


class _ContextStoreBase:
    """Shared state and read-path for ContextStore and AsyncContextStore.

    Holds all in-memory data structures and the pure-Python read methods
    (``get``, ``enrich``, ``reset``, ``active_sessions``, ``_touch_session``).
    Subclasses provide the write side (``add``, ``on_summary``) in either
    sync or async flavours.

    All state is protected by a ``threading.Lock``.  Critical sections only
    contain in-memory dict and list mutations — no I/O — so the lock is held
    for microseconds.  This is safe to acquire from both threads and coroutines
    without perceptibly stalling the event loop.
    """

    def __init__(
        self,
        summarizer: Any | None,
        *,
        include_summary: bool,
        include_actions: bool,
        lookback_seconds: float | None,
        max_actions: int | None,
        max_sessions: int | None,
    ) -> None:
        if lookback_seconds is not None and lookback_seconds <= 0:
            raise ValueError(f"lookback_seconds must be > 0, got {lookback_seconds!r}")
        if max_actions is not None and max_actions < 1:
            raise ValueError(f"max_actions must be >= 1, got {max_actions!r}")
        if max_sessions is not None and max_sessions < 1:
            raise ValueError(f"max_sessions must be >= 1, got {max_sessions!r}")

        self._include_summary = include_summary
        self._include_actions = include_actions
        self._lookback_seconds = lookback_seconds
        self._max_actions = max_actions
        self._max_sessions = max_sessions

        # session_id → latest summary text
        self._summaries: dict[str, str] = {}
        # session_id → ordered list of ActionsPayload (newest last); OrderedDict
        # used for LRU tracking when max_sessions is set.
        self._actions: OrderedDict[str, list[ActionsPayload]] = OrderedDict()
        # Tracks sessions we have already warned about to avoid log spam.
        self._warned_missing_product_id: set[str] = set()
        self._lock = threading.Lock()

        if summarizer is not None:
            if summarizer.on_summary is not None:
                logger.warning(
                    "%s: replacing existing on_summary on the provided summarizer; "
                    "the previous callback will no longer be called.",
                    type(self).__name__,
                )
            summarizer.on_summary = self.on_summary

    # ------------------------------------------------------------------
    # Internal LRU helper — must be called with self._lock held
    # ------------------------------------------------------------------

    def _touch_session(self, session_id: str) -> None:
        """Ensure session_id is tracked in _actions for LRU purposes.

        Moves an existing session to most-recently-used, or inserts an empty
        entry and evicts the least-recently-used session if the cap is exceeded.
        Must be called with ``self._lock`` already held.
        """
        if session_id in self._actions:
            self._actions.move_to_end(session_id)
        else:
            self._actions[session_id] = []
            if (
                self._max_sessions is not None
                and len(self._actions) > self._max_sessions
            ):
                evicted = next(iter(self._actions))
                del self._actions[evicted]
                self._summaries.pop(evicted, None)
                logger.debug(
                    "context_store: evicted session=%s (max_sessions=%d reached)",
                    evicted,
                    self._max_sessions,
                    extra={"session_id": evicted},
                )

    # ------------------------------------------------------------------
    # Read side — synchronous; safe to call from any coroutine
    # ------------------------------------------------------------------

    def get(
        self,
        session_id: str,
        *,
        product_id: str | None = None,
        include_summary: Any = _SENTINEL,
        include_actions: Any = _SENTINEL,
        lookback_seconds: Any = _SENTINEL,
        max_actions: Any = _SENTINEL,
    ) -> str:
        """Return the formatted session context string.

        All keyword arguments override the defaults set at construction time.

        Args:
            session_id:       The session to retrieve context for.
            product_id:       When set, scope stored actions to this product (matches
                              ingest ``ActionsPayload.product_id``). Summaries remain
                              keyed by ``session_id`` only until summariser wiring carries
                              product.
            include_summary:  Override ``include_summary`` for this call.
            include_actions:  Override ``include_actions`` for this call.
            lookback_seconds: Override ``lookback_seconds`` for this call.
            max_actions:      Override ``max_actions`` for this call.

        Returns:
            A formatted string ready to prepend to a user query, or an empty
            string if no context is available or all sections are disabled.
        """
        inc_summary = _resolve(include_summary, self._include_summary)
        inc_actions = _resolve(include_actions, self._include_actions)
        lb_seconds = _resolve(lookback_seconds, self._lookback_seconds)
        mx_actions = _resolve(max_actions, self._max_actions)

        action_key = actions_bucket_id(product_id, session_id)
        with self._lock:
            summary_text = self._summaries.get(session_id, "") if inc_summary else ""
            actions_list = (
                list(self._actions.get(action_key, [])) if inc_actions else []
            )
            fallback_key: str | None = None
            if inc_actions and not actions_list and not (product_id or "").strip():
                scoped = [
                    key
                    for key, payloads in self._actions.items()
                    if key.endswith(f"\x1f{session_id}") and payloads
                ]
                if len(scoped) == 1:
                    fallback_key = scoped[0]
                    actions_list = list(self._actions.get(fallback_key, []))
                    if session_id not in self._warned_missing_product_id:
                        logger.warning(
                            "context_store: get(session_id=%s) fell back to product-scoped "
                            "actions bucket=%s; pass product_id explicitly to avoid empty reads",
                            session_id,
                            fallback_key,
                            extra={
                                "session_id": session_id,
                                "bucket": fallback_key,
                            },
                        )
                        self._warned_missing_product_id.add(session_id)
                elif (
                    len(scoped) > 1
                    and session_id not in self._warned_missing_product_id
                ):
                    logger.warning(
                        "context_store: get(session_id=%s) found multiple product-scoped "
                        "buckets; pass product_id explicitly to disambiguate reads",
                        session_id,
                        extra={"session_id": session_id, "bucket_count": len(scoped)},
                    )
                    self._warned_missing_product_id.add(session_id)

        # Apply time filter (for per-call overrides that differ from the stored default)
        if actions_list and lb_seconds is not None:
            cutoff = time.time() - lb_seconds
            actions_list = [p for p in actions_list if p.forwarded_at >= cutoff]

        # Apply count cap (most recent N) — use len(payload.actions) not payload.count
        # to stay consistent with the actual data, not the server-supplied integer.
        if actions_list and mx_actions is not None:
            flat: list[ActionsPayload] = []
            total = 0
            for payload in reversed(actions_list):
                remaining = mx_actions - total
                if remaining <= 0:
                    break
                actual_count = len(payload.actions)
                if actual_count <= remaining:
                    flat.insert(0, payload)
                    total += actual_count
                else:
                    trimmed = replace(
                        payload,
                        actions=payload.actions[-remaining:],
                        count=remaining,
                    )
                    flat.insert(0, trimmed)
                    total += remaining
            actions_list = flat

        actions_text = _format_actions(actions_list) if actions_list else ""

        parts: list[str] = []
        if summary_text:
            parts.append(f"Summary: {summary_text}")
        if actions_text:
            parts.append(f"Recent activity:\n{actions_text}")

        return "\n\n".join(parts)

    def enrich(
        self,
        session_id: str,
        query: str,
        *,
        product_id: str | None = None,
        include_summary: Any = _SENTINEL,
        include_actions: Any = _SENTINEL,
        lookback_seconds: Any = _SENTINEL,
        max_actions: Any = _SENTINEL,
    ) -> str:
        """Enrich a user query with the session's context.

        This is the primary entry point.  Pass the result directly to your
        embedding function and then to your vector DB::

            enriched = context_store.enrich(session_id, user_message)
            results  = vector_db.query(embed(enriched))

        Synchronous — safe to call from any coroutine without blocking the
        event loop.  All keyword arguments override the defaults set at
        construction time.

        Args:
            session_id:       The session to retrieve context for.
            query:            The raw user query / chat message.
            include_summary:  Override ``include_summary`` for this call.
            include_actions:  Override ``include_actions`` for this call.
            lookback_seconds: Override ``lookback_seconds`` for this call.
            max_actions:      Override ``max_actions`` for this call.

        Returns:
            A string combining the session context and the user query.
            If no context is available the query is returned unchanged.

        Example output::

            [Session context]
            Summary: User navigated to the Dashboard and exported a CSV.

            Recent activity:
            1. Opened billing settings — /settings/billing
            2. Clicked Upgrade plan — /settings/billing

            [Query]
            How do I add a team member?
        """
        context = self.get(
            session_id,
            product_id=product_id,
            include_summary=include_summary,
            include_actions=include_actions,
            lookback_seconds=lookback_seconds,
            max_actions=max_actions,
        )
        if not context:
            return query
        return f"[Session context]\n{context}\n\n[Query]\n{query}"

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def reset(self, session_id: str, *, product_id: str | None = None) -> None:
        """Clear stored context for a session.

        Removes the rolling summary (always keyed by ``session_id``) and the
        actions bucket for ``(product_id, session_id)`` when ``product_id`` is set,
        otherwise the legacy session-only actions bucket.
        """
        action_key = actions_bucket_id(product_id, session_id)
        with self._lock:
            self._summaries.pop(session_id, None)
            self._actions.pop(action_key, None)
            if action_key != session_id:
                self._actions.pop(session_id, None)
        logger.debug(
            "context_store: reset session=%s",
            session_id,
            extra={"session_id": session_id},
        )

    @property
    def active_sessions(self) -> list[str]:
        """Session IDs that have at least one stored action or summary, in sorted order."""
        with self._lock:
            sessions = set(self._actions.keys()) | set(self._summaries.keys())
        return sorted(sessions)


# ---------------------------------------------------------------------------
# Sync variant
# ---------------------------------------------------------------------------


class ContextStore(_ContextStoreBase):
    """Thread-safe store of per-session context for query-time RAG enrichment.

    Combines a rolling LLM summary (produced by ``SessionSummarizer``) with
    the pending actions that have accumulated since the last summary, then
    injects them into a user query as a single enriched string.

    Args:
        summarizer:       Optional ``SessionSummarizer``.  When provided, the
                          store wires itself as ``summarizer.on_summary`` so
                          summaries are captured automatically.  A warning is
                          logged if an existing callback is overwritten.
        include_summary:  Default ``True``.  Include the stored rolling summary
                          in the context string.
        include_actions:  Default ``True``.  Include pending (not-yet-
                          summarised) actions in the context string.
        lookback_seconds: Default ``None`` (no limit).  When set, only actions
                          whose ``forwarded_at`` timestamp falls within the last
                          ``lookback_seconds`` seconds are included.  Also used
                          to evict stale payloads from memory on each ``add()``
                          call so the store doesn't grow unboundedly.
                          Must be > 0 when provided.
        max_actions:      Default ``None`` (no limit).  When set, only the
                          *most recent* ``max_actions`` actions are included
                          (applied after ``lookback_seconds`` filtering).
                          Must be >= 1 when provided.
        max_sessions:     Default ``None`` (no limit).  When set, the store
                          evicts the least-recently-used session when the cap
                          is reached.  Must be >= 1 when provided.
    """

    def __init__(
        self,
        summarizer: Any | None = None,
        *,
        include_summary: bool = True,
        include_actions: bool = True,
        lookback_seconds: float | None = None,
        max_actions: int | None = None,
        max_sessions: int | None = None,
    ) -> None:
        super().__init__(
            summarizer,
            include_summary=include_summary,
            include_actions=include_actions,
            lookback_seconds=lookback_seconds,
            max_actions=max_actions,
            max_sessions=max_sessions,
        )

    # ------------------------------------------------------------------
    # Write side — wire to client callbacks
    # ------------------------------------------------------------------

    def add(self, payload: ActionsPayload) -> None:
        """Receive an actions batch and store it for the session.

        Wire directly to ``on_actions``::

            client.on_actions(context_store.add)

        Stale payloads (older than ``lookback_seconds``) are evicted on each
        call so the per-session list does not grow unboundedly.

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        session_id = payload.session_id or "unknown"
        bucket = actions_bucket_id(getattr(payload, "product_id", None), session_id)
        with self._lock:
            self._touch_session(bucket)
            self._actions[bucket].append(payload)

            if self._lookback_seconds is not None:
                cutoff = time.time() - self._lookback_seconds
                self._actions[bucket] = [
                    p for p in self._actions[bucket] if p.forwarded_at >= cutoff
                ]

        logger.debug(
            "context_store: stored session=%s actions=%d",
            session_id,
            len(payload.actions),
            extra={
                "session_id": session_id,
                "product_id": getattr(payload, "product_id", None),
            },
        )

    def on_summary(self, session_id: str, summary_text: str) -> None:
        """Store the latest LLM summary for a session.

        Automatically wired when a ``summarizer`` is passed to the constructor.
        Can also be called manually or wired to ``SessionSummarizer.on_summary``.

        Note: pending actions for this session are **not** cleared here —
        ``SessionSummarizer`` already resets its own history, but the
        ``ContextStore`` keeps any actions that arrived *after* the summariser
        took its snapshot (i.e. actions since the last summary).

        Args:
            session_id:   Session identifier.
            summary_text: Prose summary produced by the LLM.
        """
        with self._lock:
            self._touch_session(session_id)
            self._summaries[session_id] = summary_text
        logger.debug(
            "context_store: stored summary session=%s",
            session_id,
            extra={"session_id": session_id},
        )


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


class AsyncContextStore(_ContextStoreBase):
    """Async version of ``ContextStore`` for use with ``AsyncConnectorClient``.

    ``add`` and ``on_summary`` are coroutines so they can be awaited directly
    in an async pipeline.  ``get`` and ``enrich`` remain synchronous since they
    only read in-memory state and are safe to call from any coroutine without
    blocking the event loop.

    Locking model
    -------------
    Internally this class uses a ``threading.Lock`` (not an ``asyncio.Lock``)
    to protect its in-memory dicts.  This is intentional: the critical section
    contains only fast in-memory mutations — no ``await``, no I/O.  A
    ``threading.Lock`` held for a few microseconds is imperceptible to the
    event loop.  Replacing it with an ``asyncio.Lock`` would add overhead
    without benefit because the lock is never held across a yield point.

    Args:
        summarizer:       Optional ``AsyncSessionSummarizer``.  When provided,
                          the store wires itself as ``summarizer.on_summary`` so
                          summaries are captured automatically.
        include_summary:  Default ``True``.  Include the stored rolling summary
                          in the context string.
        include_actions:  Default ``True``.  Include pending actions.
        lookback_seconds: Default ``None`` (no limit).  Must be > 0 when
                          provided.
        max_actions:      Default ``None`` (no limit).  Must be >= 1 when
                          provided.
        max_sessions:     Default ``None`` (no limit).  Must be >= 1 when
                          provided.
    """

    def __init__(
        self,
        summarizer: Any | None = None,
        *,
        include_summary: bool = True,
        include_actions: bool = True,
        lookback_seconds: float | None = None,
        max_actions: int | None = None,
        max_sessions: int | None = None,
    ) -> None:
        super().__init__(
            summarizer,
            include_summary=include_summary,
            include_actions=include_actions,
            lookback_seconds=lookback_seconds,
            max_actions=max_actions,
            max_sessions=max_sessions,
        )

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    async def add(self, payload: ActionsPayload) -> None:
        """Receive an actions batch and store it for the session.

        Wire directly to ``on_actions``::

            client.on_actions(context_store.add)

        Stale payloads (older than ``lookback_seconds``) are evicted on each
        call so the per-session list does not grow unboundedly.

        The internal ``threading.Lock`` is held only during the in-memory
        dict mutation — no I/O occurs inside the lock — so this coroutine
        never stalls the event loop.

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        session_id = payload.session_id or "unknown"
        bucket = actions_bucket_id(getattr(payload, "product_id", None), session_id)
        with self._lock:
            self._touch_session(bucket)
            self._actions[bucket].append(payload)

            if self._lookback_seconds is not None:
                cutoff = time.time() - self._lookback_seconds
                self._actions[bucket] = [
                    p for p in self._actions[bucket] if p.forwarded_at >= cutoff
                ]

        logger.debug(
            "context_store: stored session=%s actions=%d",
            session_id,
            len(payload.actions),
            extra={
                "session_id": session_id,
                "product_id": getattr(payload, "product_id", None),
            },
        )

    async def on_summary(self, session_id: str, summary_text: str) -> None:
        """Store the latest LLM summary for a session.

        Automatically wired when a ``summarizer`` is passed to the constructor.
        Can also be called manually or wired to ``AsyncSessionSummarizer.on_summary``.

        Note: pending actions for this session are **not** cleared here —
        ``AsyncSessionSummarizer`` already resets its own history, but the
        ``AsyncContextStore`` keeps any actions that arrived *after* the
        summariser took its snapshot (i.e. actions since the last summary).

        The internal ``threading.Lock`` is held only during the in-memory
        dict mutation — no I/O occurs inside the lock.

        Args:
            session_id:   Session identifier.
            summary_text: Prose summary produced by the LLM.
        """
        with self._lock:
            self._touch_session(session_id)
            self._summaries[session_id] = summary_text
        logger.debug(
            "context_store: stored summary session=%s",
            session_id,
            extra={"session_id": session_id},
        )


__all__ = ["AsyncContextStore", "ContextStore", "actions_bucket_id"]
