"""autoplay_sdk.summarizer — Client-side session summarizer for context-window management.

Accumulates real-time user actions per session.  When the number of actions
reaches a configurable threshold, the summarizer calls your LLM with a
prompt to produce a concise prose summary, then fires an ``on_summary``
callback with the result and resets the session's history.

This keeps your RAG context window compact regardless of how long a session
runs — instead of growing unboundedly, each session is represented by a
rolling summary of the most recent ``threshold`` actions.

Sync usage::

    import openai
    from autoplay_sdk import ConnectorClient
    from autoplay_sdk.summarizer import SessionSummarizer

    openai_client = openai.OpenAI()

    def my_llm(prompt: str) -> str:
        return openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content

    def store_summary(session_id: str, summary: str) -> None:
        print(f"[{session_id}] {summary}")

    summarizer = SessionSummarizer(
        llm=my_llm,
        threshold=10,          # summarize every 10 actions
        on_summary=store_summary,
        # prompt=custom_prompt,  # optional — uses built-in default
    )

    ConnectorClient(url=URL, token=TOKEN) \\
        .on_actions(summarizer.add) \\
        .run()

Async usage::

    from autoplay_sdk.summarizer import AsyncSessionSummarizer

    async def my_async_llm(prompt: str) -> str:
        r = await async_openai.chat.completions.create(...)
        return r.choices[0].message.content

    async def store_summary(session_id: str, summary: str) -> None:
        await db.save(session_id, summary)

    summarizer = AsyncSessionSummarizer(
        llm=my_async_llm,
        threshold=10,
        on_summary=store_summary,
    )

    async with AsyncConnectorClient(url=URL, token=TOKEN) as client:
        client.on_actions(summarizer.add)
        await client.run()

Composing with RagPipeline::

    from autoplay_sdk.rag import RagPipeline
    from autoplay_sdk.summarizer import SessionSummarizer

    summarizer = SessionSummarizer(llm=my_llm, threshold=10)
    pipeline   = RagPipeline(embed=embed_fn, upsert=upsert_fn, summarizer=summarizer)

    client.on_actions(pipeline.on_actions).on_summary(pipeline.on_summary).run()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable

from autoplay_sdk.exceptions import SdkConfigError
from autoplay_sdk.metrics import SdkMetricsHook, _safe_call
from autoplay_sdk.models import ActionsPayload

logger = logging.getLogger(__name__)

# Sentinel that signals a per-session worker to flush state and exit cleanly.
_SESSION_STOP = object()

# ---------------------------------------------------------------------------
# Default prompt
# ---------------------------------------------------------------------------

DEFAULT_PROMPT = """\
You are summarising a user's in-app session for a RAG pipeline.
Your summary will be embedded and stored in a vector database to provide
context for a chatbot or AI assistant.

Write a concise 2-3 sentence summary of what the user did, focusing on:
- Which features or pages they visited
- What actions they performed
- Any clear intent or goal you can infer

Actions:
{actions}

Summary:"""
"""Built-in prompt template used by ``SessionSummarizer`` and
``AsyncSessionSummarizer`` when no custom ``prompt`` is provided.

The template contains one required placeholder: ``{actions}``, which is
substituted with the formatted action list before the LLM call.  The result
is a 2–3 sentence prose summary optimised for vector embedding.

Override when you need a different tone, language, output format (e.g. JSON),
or domain-specific focus::

    MY_PROMPT = \"\"\"
    Summarise the user's actions as a comma-separated list of page names.
    Actions: {actions}
    \"\"\"

    summarizer = SessionSummarizer(llm=my_llm, threshold=10, prompt=MY_PROMPT)
"""


def _format_actions(payloads: list[ActionsPayload]) -> str:
    """Format a list of ActionsPayload into a numbered action list for the prompt."""
    lines: list[str] = []
    n = 1
    for payload in payloads:
        for action in payload.actions:
            lines.append(f"{n}. {action.to_text()}")
            n += 1
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync summarizer
# ---------------------------------------------------------------------------


class SessionSummarizer:
    """Accumulates actions per session and summarises them when a threshold is reached.

    Args:
        llm:            ``(prompt: str) -> str`` — any synchronous LLM callable.
                        Receives the formatted prompt and must return the summary
                        as a plain string.
        threshold:      Number of **individual actions** (not batches) to
                        accumulate before triggering a summarisation.  Must be
                        >= 1.  Default 10.
        prompt:         Custom prompt template string.  Must contain ``{actions}``
                        as a placeholder for the formatted action list.  If
                        ``None``, the built-in default prompt is used.
        on_summary:     ``(session_id: str, summary: str) -> None`` — called
                        after each summarisation.  Wire this to your storage,
                        vector store, or ``RagPipeline``.  Can also be set later
                        by assigning to ``summarizer.on_summary``.
        format_actions: ``(payloads: list[ActionsPayload]) -> str`` — optional
                        callable that converts accumulated payloads into the text
                        substituted into the ``{actions}`` placeholder.  Defaults
                        to a simple numbered action list.  Override to use a custom
                        format such as a page-grouped timeline.
        max_sessions:   Maximum number of distinct sessions to track at once.
                        When the cap is exceeded the least-recently-used session
                        is evicted to bound memory for long-lived processes
                        handling high-cardinality traffic.  ``None`` (default)
                        means unbounded.
    """

    def __init__(
        self,
        llm: Callable[[str], str],
        threshold: int = 10,
        prompt: str | None = None,
        on_summary: Callable[[str, str], None] | None = None,
        format_actions: Callable[[list[ActionsPayload]], str] | None = None,
        max_sessions: int | None = None,
    ) -> None:
        if threshold < 1:
            raise SdkConfigError(f"threshold must be >= 1, got {threshold!r}")
        self._llm = llm
        self._threshold = threshold
        self._prompt_template = prompt or DEFAULT_PROMPT
        self.on_summary = on_summary
        self._format_actions = format_actions or _format_actions
        self._max_sessions = max_sessions

        # session_id → list of ActionsPayload batches (LRU-ordered)
        self._history: OrderedDict[str, list[ActionsPayload]] = OrderedDict()
        # session_id → total action count (LRU-ordered, mirrors _history)
        self._counts: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add(self, payload: ActionsPayload) -> None:
        """Receive an actions batch, accumulate, and summarise if threshold is hit.

        Wire directly to ``on_actions``::

            client.on_actions(summarizer.add)

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        session_id = payload.session_id or "unknown"
        action_count = len(payload.actions)

        with self._lock:
            # Touch session (move to end = most recently used).
            if session_id in self._history:
                self._history.move_to_end(session_id)
                self._counts.move_to_end(session_id)
            else:
                self._history[session_id] = []
                self._counts[session_id] = 0
                # Evict least-recently-used session if the cap is exceeded.
                if (
                    self._max_sessions is not None
                    and len(self._history) > self._max_sessions
                ):
                    self._history.popitem(last=False)
                    self._counts.popitem(last=False)

            self._history[session_id].append(payload)
            self._counts[session_id] += action_count
            should_summarise = self._counts[session_id] >= self._threshold
            if should_summarise:
                history_snapshot = list(self._history[session_id])
                del self._history[session_id]
                del self._counts[session_id]

        if should_summarise:
            self._summarise(session_id, history_snapshot)

    def get_context(self, session_id: str) -> str:
        """Return the accumulated (not-yet-summarised) actions as text.

        Useful for including partial session context in a RAG query before
        the threshold is reached.

        Args:
            session_id: The session identifier.

        Returns:
            Formatted action list string, or empty string if no history.
        """
        with self._lock:
            history = list(self._history.get(session_id, []))
        return self._format_actions(history)

    def reset(self, session_id: str) -> None:
        """Clear accumulated history for a session without summarising.

        Args:
            session_id: The session to reset.
        """
        with self._lock:
            self._history.pop(session_id, None)
            self._counts.pop(session_id, None)

    @property
    def active_sessions(self) -> list[str]:
        """List of session IDs with pending (not-yet-summarised) actions."""
        with self._lock:
            return [sid for sid, count in self._counts.items() if count > 0]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _summarise(self, session_id: str, history: list[ActionsPayload]) -> None:
        actions_text = self._format_actions(history)
        action_count = sum(len(p.actions) for p in history)
        try:
            prompt = self._prompt_template.format(actions=actions_text)
        except KeyError as exc:
            logger.error(
                "summarizer: prompt template missing placeholder for session=%s — "
                "ensure the template contains {actions}: %s",
                session_id,
                exc,
                exc_info=True,
                extra={"session_id": session_id},
            )
            with self._lock:
                existing = self._history.get(session_id, [])
                self._history[session_id] = history + existing
                self._counts[session_id] = (
                    self._counts.get(session_id, 0) + action_count
                )
            return

        summary: str | None = None
        t0 = time.perf_counter()
        try:
            summary = self._llm(prompt)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(
                "summarizer: summarised session=%s actions=%d elapsed_ms=%.1f",
                session_id,
                action_count,
                elapsed_ms,
                extra={"session_id": session_id, "action_count": action_count},
            )
        except Exception as exc:
            logger.error(
                "summarizer: LLM call failed for session=%s — restoring history: %s",
                session_id,
                exc,
                exc_info=True,
                extra={"session_id": session_id},
            )
            with self._lock:
                existing = self._history.get(session_id, [])
                self._history[session_id] = history + existing
                self._counts[session_id] = (
                    self._counts.get(session_id, 0) + action_count
                )
            return

        if self.on_summary is not None:
            try:
                self.on_summary(session_id, summary)
            except Exception as exc:
                logger.error(
                    "summarizer: on_summary callback raised for session=%s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                    extra={"session_id": session_id},
                )


# ---------------------------------------------------------------------------
# Async summarizer
# ---------------------------------------------------------------------------

# How long a per-session worker idles before exiting to reclaim memory.
# Workers are recreated on the next add() call for that session.
_WORKER_IDLE_TIMEOUT_S = 300.0


def _worker_done_callback(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Log unhandled exceptions from fire-and-forget session worker tasks.

    Attached via ``task.add_done_callback`` so that exceptions that escape
    ``_session_worker`` (e.g. unexpected ``CancelledError`` propagation or
    programmer errors) are surfaced in the log rather than silently discarded
    by asyncio's default behaviour.
    """
    if not task.cancelled() and task.exception():
        logger.error(
            "summarizer: session worker raised an unhandled exception",
            exc_info=task.exception(),
        )


class AsyncSessionSummarizer:
    """Async version of ``SessionSummarizer`` for use with ``AsyncConnectorClient``.

    ``llm`` and ``on_summary`` are async callables (coroutines).

    Ordering guarantee
    ------------------
    Each session gets a dedicated background ``asyncio.Task`` that processes
    payloads sequentially.  ``add()`` enqueues and returns immediately, so the
    SSE stream is never stalled waiting for an LLM call to finish.  Because
    each worker processes one payload at a time — accumulate → threshold check
    → LLM call → restore on failure — concurrent LLM calls for the same
    session are impossible by construction.  ``on_summary`` callbacks always
    fire in the order actions were received, even across LLM failures.

    Workers exit automatically after ``_WORKER_IDLE_TIMEOUT_S`` (5 min) of
    inactivity and are recreated transparently on the next ``add()``.

    Args:
        llm:            ``async (prompt: str) -> str``
        threshold:      Number of individual actions before summarisation.  Must
                        be >= 1.  Default 10.
        prompt:         Custom prompt template (must contain ``{actions}``).
        on_summary:     ``async (session_id: str, summary: str) -> None``
        format_actions: ``(payloads: list[ActionsPayload]) -> str`` — optional
                        callable that converts accumulated payloads into the text
                        substituted into the ``{actions}`` placeholder.  Defaults
                        to a simple numbered action list.  Override to use a custom
                        format such as a page-grouped timeline.
        max_queue_size: Maximum number of payloads that can be buffered per-session
                        queue before new arrivals are dropped.  ``None`` (default)
                        means unbounded — use a positive integer in production to
                        cap memory under a slow-LLM / traffic-spike scenario.
        metrics:        Optional ``SdkMetricsHook`` implementation.  Receives
                        per-session LLM summarization latency after each
                        successful call.  See ``autoplay_sdk.metrics``.
    """

    def __init__(
        self,
        llm: Callable[[str], Awaitable[str]],
        threshold: int = 10,
        prompt: str | None = None,
        on_summary: Callable[[str, str], Awaitable[None]] | None = None,
        format_actions: Callable[[list[ActionsPayload]], str] | None = None,
        max_queue_size: int | None = None,
        metrics: SdkMetricsHook | None = None,
    ) -> None:
        if threshold < 1:
            raise SdkConfigError(f"threshold must be >= 1, got {threshold!r}")
        self._llm = llm
        self._threshold = threshold
        self._prompt_template = prompt or DEFAULT_PROMPT
        self.on_summary = on_summary
        self._format_actions = format_actions or _format_actions
        self._max_queue_size = max_queue_size
        self._metrics = metrics

        # Accumulated (not-yet-summarised) payloads and action counts per session.
        self._history: dict[str, list[ActionsPayload]] = defaultdict(list)
        self._counts: dict[str, int] = defaultdict(int)
        # Per-session queues and worker tasks.  Protected by _state_lock.
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        # Protects _history, _counts, _queues, and _workers.
        self._state_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def add(self, payload: ActionsPayload) -> None:
        """Enqueue an actions batch for sequential processing.

        Returns immediately — the payload is processed by a per-session
        background worker, so this never blocks on the LLM call.

        Wire directly to ``on_actions``::

            client.on_actions(summarizer.add)
        """
        session_id = payload.session_id or "unknown"
        async with self._state_lock:
            if session_id not in self._queues:
                q: asyncio.Queue = asyncio.Queue(
                    maxsize=self._max_queue_size
                    if self._max_queue_size is not None
                    else 0
                )
                self._queues[session_id] = q
                task = asyncio.get_running_loop().create_task(
                    self._session_worker(session_id, q),
                    name=f"summarizer-worker-{session_id}",
                )
                task.add_done_callback(_worker_done_callback)
                self._workers[session_id] = task
            q = self._queues[session_id]
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            product_id = getattr(payload, "product_id", None)
            logger.warning(
                "summarizer: per-session queue full — dropping payload for session=%s",
                session_id,
                extra={"session_id": session_id, "product_id": product_id},
            )
            _safe_call(
                self._metrics,
                "record_event_dropped",
                reason="queue_full",
                event_type="actions",
                session_id=session_id,
                product_id=product_id,
            )

    async def get_context(self, session_id: str) -> str:
        """Return the accumulated (not-yet-summarised) actions as text.

        Useful for including partial session context in a RAG query before
        the threshold is reached.

        Args:
            session_id: The session identifier.

        Returns:
            Formatted action list string, or empty string if no history.
        """
        async with self._state_lock:
            history = list(self._history.get(session_id, []))
        return self._format_actions(history)

    async def reset(self, session_id: str) -> None:
        """Clear accumulated history for a session without summarising.

        Sends a stop sentinel to the session worker so it drains cleanly
        and removes itself.  Safe to call even if no add() has been called
        for the session yet.
        """
        async with self._state_lock:
            q = self._queues.get(session_id)
        if q is not None:
            await q.put(_SESSION_STOP)
        else:
            async with self._state_lock:
                self._history.pop(session_id, None)
                self._counts.pop(session_id, None)

    async def flush(self) -> None:
        """Wait until all queued payloads have been fully processed.

        Blocks until every per-session worker has drained its queue.  Useful
        in tests and graceful-shutdown flows to ensure all ``add()`` calls
        have been processed before inspecting state or exiting.

        Example::

            await summarizer.add(payload)
            await summarizer.flush()
            assert await summarizer.get_context(session_id) == ""
        """
        async with self._state_lock:
            queues = list(self._queues.values())
        if queues:
            await asyncio.gather(*[asyncio.shield(q.join()) for q in queues])

    @property
    async def active_sessions(self) -> list[str]:
        """List of session IDs with pending (not-yet-summarised) actions.

        This is an *async property* — access it with ``await``::

            sessions = await summarizer.active_sessions

        Returns:
            Sorted list of session IDs whose action count is above zero
            (i.e. actions have arrived since the last summarisation).
        """
        async with self._state_lock:
            return sorted(sid for sid, count in self._counts.items() if count > 0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _session_worker(self, session_id: str, q: asyncio.Queue) -> None:
        """Drain the per-session queue, processing one payload at a time.

        Exits on a stop sentinel or after idle for ``_WORKER_IDLE_TIMEOUT_S``
        seconds.  In both cases it removes its own entries from the registries.
        """
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=_WORKER_IDLE_TIMEOUT_S)
            except asyncio.TimeoutError:
                async with self._state_lock:
                    # Only remove our queue if add() hasn't already replaced it.
                    if self._queues.get(session_id) is q:
                        self._queues.pop(session_id, None)
                        self._workers.pop(session_id, None)
                        # Release sub-threshold history so long-lived processes
                        # handling high-cardinality sessions do not leak memory.
                        self._history.pop(session_id, None)
                        self._counts.pop(session_id, None)
                logger.debug(
                    "summarizer: worker for session=%s exited after idle",
                    session_id,
                    extra={"session_id": session_id},
                )
                return

            try:
                if item is _SESSION_STOP:
                    async with self._state_lock:
                        if self._queues.get(session_id) is q:
                            self._queues.pop(session_id, None)
                            self._workers.pop(session_id, None)
                        self._history.pop(session_id, None)
                        self._counts.pop(session_id, None)
                    return

                action_count = len(item.actions)
                async with self._state_lock:
                    self._history[session_id].append(item)
                    self._counts[session_id] += action_count
                    should_summarise = self._counts[session_id] >= self._threshold
                    if should_summarise:
                        history_snapshot = list(self._history[session_id])
                        del self._history[session_id]
                        del self._counts[session_id]

                if should_summarise:
                    await self._summarise(session_id, history_snapshot)
            finally:
                q.task_done()

    async def _summarise(self, session_id: str, history: list[ActionsPayload]) -> None:
        actions_text = self._format_actions(history)
        action_count = sum(len(p.actions) for p in history)
        try:
            prompt = self._prompt_template.format(actions=actions_text)
        except KeyError as exc:
            logger.error(
                "summarizer: prompt template missing placeholder for session=%s — "
                "ensure the template contains {actions}: %s",
                session_id,
                exc,
                exc_info=True,
                extra={"session_id": session_id},
            )
            async with self._state_lock:
                self._history[session_id] = history + self._history[session_id]
                self._counts[session_id] += action_count
            return

        summary: str | None = None
        t0 = time.perf_counter()
        try:
            summary = await self._llm(prompt)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(
                "summarizer: summarised session=%s actions=%d elapsed_ms=%.1f",
                session_id,
                action_count,
                elapsed_ms,
                extra={"session_id": session_id, "action_count": action_count},
            )
            _safe_call(
                self._metrics,
                "record_summarizer_latency",
                session_id=session_id,
                elapsed_ms=elapsed_ms,
                action_count=action_count,
            )
        except Exception as exc:
            logger.error(
                "summarizer: LLM call failed for session=%s — restoring history: %s",
                session_id,
                exc,
                exc_info=True,
                extra={"session_id": session_id},
            )
            # Prepend the snapshot so already-queued payloads remain in order.
            async with self._state_lock:
                self._history[session_id] = history + self._history[session_id]
                self._counts[session_id] += action_count
            return

        if self.on_summary is not None:
            try:
                result = self.on_summary(session_id, summary)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.error(
                    "summarizer: on_summary callback raised for session=%s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                    extra={"session_id": session_id},
                )
