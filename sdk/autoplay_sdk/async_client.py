"""autoplay_sdk.async_client — Async-native SSE client for Autoplay connectors.

Identical feature set to ``ConnectorClient`` but built for ``asyncio``-first
environments: LangChain, LlamaIndex, FastAPI backends, and any RAG pipeline
that uses ``async/await``.

Use ``async def`` callbacks so you can ``await`` vector store upserts, LLM
embedding calls, or database writes directly inside your callback without
blocking the event loop or spawning extra threads.

.. warning:: Sync callbacks block the event loop

    For convenience, plain ``def`` callbacks are accepted.  However, a sync
    callback that blocks — for example a synchronous DB write, a ``requests``
    HTTP call, or ``time.sleep`` — will stall the **entire event loop** for
    the duration of that call, delaying all other coroutines in your process.

    Always use ``async def`` for callbacks that do any I/O.  If you must call
    blocking code from an async callback, offload it to a thread::

        async def on_actions(payload: ActionsPayload) -> None:
            await asyncio.to_thread(blocking_sync_function, payload)

Quickstart::

    import asyncio
    from autoplay_sdk import AsyncConnectorClient, ActionsPayload

    async def on_actions(payload: ActionsPayload) -> None:
        text = payload.to_text()
        await vector_store.upsert(payload.session_id, await embed(text))

    async def main():
        async with AsyncConnectorClient(url="https://host/stream/my_product",
                                        token="uk_live_...") as client:
            client.on_actions(on_actions)
            await client.run()

    asyncio.run(main())

Background usage (non-blocking inside an existing event loop)::

    client = AsyncConnectorClient(url="...", token="...")
    client.on_actions(on_actions)
    task = client.run_in_background()  # returns asyncio.Task

    # do other async work ...
    await asyncio.sleep(60)

    client.stop()
    await task

Reconnect policy
----------------
The client reconnects automatically on any transient network failure.  The
policy is:

- First retry after ``initial_backoff_s`` seconds (default 1 s).
- Each subsequent retry doubles the wait, capped at ``max_backoff_s``
  (default 30 s).
- A 0–10 % additive jitter is added to each sleep to spread thundering-herd
  reconnects across multiple processes.
- Retries continue indefinitely unless ``max_retries`` is set (default
  ``None``).  When exhausted, a ``RuntimeError`` is raised.
- HTTP 401, 403, and 404 responses are **fatal** — they raise immediately
  without retrying.

Per-session callback isolation
-------------------------------
Each incoming payload is dispatched under a per-session ``asyncio.Semaphore``
(``session_concurrency``).  This limits concurrent in-flight callback
executions per session so a slow callback for session A never delays
delivery for session B.  The SSE reader itself is not under the semaphore —
events keep arriving from the network regardless of how long your callbacks
take.

Lifecycle hooks
---------------
Use ``on_connect`` and ``on_disconnect`` to react to connection events::

    async def reset_state():
        await context_store.reset_all()

    client = AsyncConnectorClient(url="...", token="...", on_connect=reset_state)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from autoplay_sdk.exceptions import SdkUpstreamError
from autoplay_sdk.metrics import SdkMetricsHook, _safe_call
from autoplay_sdk.models import ActionsPayload, SummaryPayload
from autoplay_sdk.stream_auth import resolve_connector_bearer_token

logger = logging.getLogger(__name__)

# Maximum number of per-session semaphores to keep in memory.
# Evicts the least-recently-used entry when the cap is exceeded so long-lived
# processes serving many unique sessions do not leak memory indefinitely.
_MAX_SESSION_SEMAPHORES = 10_000

# Callbacks may be sync or async; coroutine detection happens at dispatch time.
ActionCallback = Callable[[ActionsPayload], Any]
SummaryCallback = Callable[[SummaryPayload], Any]
LifecycleCallback = Callable[[], Any]


class AsyncConnectorClient:
    """Async SSE client that dispatches typed payload models to async callbacks.

    Designed for ``asyncio``-first RAG pipelines where callbacks need to
    ``await`` embedding APIs, vector stores, or databases without blocking.

    Each payload is dispatched under a per-session ``asyncio.Semaphore``
    (``session_concurrency``) so sessions never block each other.

    Reconnect policy: exponential backoff starting at ``initial_backoff_s``
    (default 1 s), doubling each attempt up to ``max_backoff_s`` (default
    30 s), with ±10 % jitter.  HTTP 401/403/404 are immediately fatal.
    See the module docstring for the full contract.

    Args:
        url:                 Full URL to ``GET /stream/{product_id}`` on the connector.
        token:               Unkey API key for this product (``uk_live_...``).
                             If empty, uses ``AUTOPLAY_APP_UNKEY_TOKEN`` (stream /
                             tour events after proactive popup).
        connect_timeout:     Seconds to wait for the initial TCP connection before
                             raising an error and triggering a reconnect.  Does not
                             limit how long the stream can stay open.  Default: 10.0.
        session_concurrency: Maximum number of concurrent in-flight callback tasks
                             per session.  Default: 4.
        initial_backoff_s:   Seconds to wait before the first reconnect attempt.
                             Default: 1.0.
        max_backoff_s:       Upper bound on the reconnect wait.  Default: 30.0.
        max_retries:         Maximum reconnect attempts before raising
                             ``RuntimeError``.  ``None`` retries forever.
                             Default: ``None``.
        on_connect:          Optional async or sync ``() -> None`` called each time
                             the SSE connection is successfully established.
        on_disconnect:       Optional async or sync ``() -> None`` called each time
                             the SSE connection is lost.
        metrics:             Optional ``SdkMetricsHook`` implementation for
                             dropped-event counters and queue-depth gauges.
    """

    def __init__(
        self,
        url: str,
        token: str = "",
        connect_timeout: float = 10.0,
        session_concurrency: int = 4,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        max_retries: int | None = None,
        on_connect: LifecycleCallback | None = None,
        on_disconnect: LifecycleCallback | None = None,
        metrics: SdkMetricsHook | None = None,
    ) -> None:
        if connect_timeout <= 0:
            raise ValueError(f"connect_timeout must be > 0, got {connect_timeout!r}")
        if session_concurrency < 1:
            raise ValueError(
                f"session_concurrency must be >= 1, got {session_concurrency!r}"
            )
        if initial_backoff_s <= 0:
            raise ValueError(
                f"initial_backoff_s must be > 0, got {initial_backoff_s!r}"
            )
        if max_backoff_s < initial_backoff_s:
            raise ValueError("max_backoff_s must be >= initial_backoff_s")
        if max_retries is not None and max_retries < 0:
            raise ValueError(f"max_retries must be >= 0 or None, got {max_retries!r}")
        self._url = url
        self._token = resolve_connector_bearer_token(token)
        self._connect_timeout = connect_timeout
        self._session_concurrency = session_concurrency
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._max_retries = max_retries
        self._on_connect_cb = on_connect
        self._on_disconnect_cb = on_disconnect
        self._metrics = metrics
        self._actions_cb: ActionCallback | None = None
        self._summary_cb: SummaryCallback | None = None
        self._running = False
        # Per-session semaphores — created lazily, keyed by session_id.
        # OrderedDict + LRU eviction caps memory for long-lived, high-cardinality processes.
        self._session_semaphores: OrderedDict[str, asyncio.Semaphore] = OrderedDict()
        # Count of dispatch tasks currently holding a semaphore slot.
        self._active_dispatches: int = 0

    # ------------------------------------------------------------------
    # Builder interface
    # ------------------------------------------------------------------

    def on_actions(self, fn: ActionCallback) -> "AsyncConnectorClient":
        """Register a callback for ``actions`` events.

        Called every time the connector extracts a batch of UI actions from a
        user session.  Runs under the per-session semaphore, so concurrent
        calls for the same session are bounded by ``session_concurrency``.

        Args:
            fn: ``async def fn(payload: ActionsPayload) -> None``.
                Call ``payload.to_text()`` for an embedding-ready string.
                Plain ``def`` functions are accepted but block the event loop
                for their duration — use ``async def`` for any I/O.

        Returns:
            self — for method chaining.
        """
        self._actions_cb = fn
        return self

    def on_summary(self, fn: SummaryCallback) -> "AsyncConnectorClient":
        """Register a callback for ``summary`` events.

        Called when the connector's LLM summariser produces a prose summary of
        a session.  Useful for keeping a compact, up-to-date context window in
        your RAG pipeline.

        Args:
            fn: ``async def fn(payload: SummaryPayload) -> None``.
                Call ``payload.to_text()`` for the prose summary string.
                Plain ``def`` functions are accepted but block the event loop
                for their duration — use ``async def`` for any I/O.

        Returns:
            self — for method chaining.
        """
        self._summary_cb = fn
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to the SSE stream and process events until stopped.

        Reconnects automatically with exponential backoff.  See the class
        docstring for the full reconnect policy.  Raises ``RuntimeError`` if
        ``max_retries`` is set and exhausted.

        Intended to be the main coroutine in your async application::

            await client.run()
        """
        self._running = True
        backoff = self._initial_backoff_s
        retry_count = 0
        headers = {"Accept": "text/event-stream"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        timeout = httpx.Timeout(None, connect=self._connect_timeout)

        while self._running:
            try:
                logger.info(
                    "autoplay_sdk: connecting to %s",
                    self._url,
                    extra={"url": self._url},
                )
                async with httpx.AsyncClient(timeout=timeout) as http:
                    async with aconnect_sse(
                        http, "GET", self._url, headers=headers
                    ) as source:
                        logger.info(
                            "autoplay_sdk: connected",
                            extra={"url": self._url},
                        )
                        backoff = self._initial_backoff_s
                        retry_count = 0
                        await self._fire_on_connect()
                        async for sse in source.aiter_sse():
                            if not self._running:
                                return
                            await self._handle(sse)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403, 404):
                    logger.error(
                        "autoplay_sdk: fatal HTTP %d — check URL and token",
                        exc.response.status_code,
                        exc_info=exc,
                        extra={
                            "http_status": exc.response.status_code,
                            "url": self._url,
                        },
                    )
                    raise
                retry_count += 1
                logger.warning(
                    "autoplay_sdk: HTTP %d — retrying in %.0fs (attempt %d)",
                    exc.response.status_code,
                    backoff,
                    retry_count,
                    extra={
                        "http_status": exc.response.status_code,
                        "url": self._url,
                        "retry_count": retry_count,
                    },
                )
                await self._fire_on_disconnect()
            except asyncio.CancelledError:
                logger.info("autoplay_sdk: cancelled", extra={"url": self._url})
                self._running = False
                return
            except Exception as exc:
                retry_count += 1
                logger.warning(
                    "autoplay_sdk: connection lost (%s) — retrying in %.0fs (attempt %d)",
                    exc,
                    backoff,
                    retry_count,
                    extra={"url": self._url, "retry_count": retry_count},
                )
                await self._fire_on_disconnect()

            if self._running:
                if self._max_retries is not None and retry_count > self._max_retries:
                    logger.critical(
                        "autoplay_sdk: max_retries=%d exhausted — giving up",
                        self._max_retries,
                        extra={"url": self._url, "retry_count": retry_count},
                    )
                    self._running = False
                    raise SdkUpstreamError(
                        f"autoplay_sdk: max_retries={self._max_retries} exhausted "
                        f"after {retry_count} attempts"
                    )
                jitter = random.uniform(0, backoff * 0.1)
                await asyncio.sleep(backoff + jitter)
                backoff = min(backoff * 2, self._max_backoff_s)

        logger.info("autoplay_sdk: stopped", extra={"url": self._url})

    def run_in_background(self) -> asyncio.Task:
        """Schedule ``run()`` as a background ``asyncio.Task``.

        Returns immediately.  The task runs concurrently with other
        coroutines in the current event loop.  Call ``stop()`` and then
        ``await`` the returned task to shut down cleanly.

        Returns:
            ``asyncio.Task`` wrapping ``run()``.

        Example::

            task = client.run_in_background()
            await do_other_async_work()
            client.stop()
            await task
        """
        return asyncio.get_running_loop().create_task(self.run())

    def stop(self) -> None:
        """Signal the client to stop after the current event is processed.

        Sets an internal flag that causes ``run()`` to exit cleanly after
        finishing the current dispatch cycle.  Safe to call from any thread
        or coroutine.  If you started the client with ``run_in_background()``,
        await the returned task after calling ``stop()`` to ensure a clean
        shutdown.
        """
        self._running = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AsyncConnectorClient":
        """Support ``async with AsyncConnectorClient(...) as client:`` usage."""
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Call ``stop()`` automatically when exiting the ``async with`` block."""
        self.stop()

    def __repr__(self) -> str:
        return f"AsyncConnectorClient(url={self._url!r}, running={self._running})"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fire_on_connect(self) -> None:
        if self._on_connect_cb is not None:
            try:
                result = self._on_connect_cb()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: on_connect callback raised: %s",
                    exc,
                    exc_info=True,
                    extra={"url": self._url},
                )

    async def _fire_on_disconnect(self) -> None:
        if self._on_disconnect_cb is not None:
            try:
                result = self._on_disconnect_cb()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: on_disconnect callback raised: %s",
                    exc,
                    exc_info=True,
                    extra={"url": self._url},
                )

    async def _handle(self, sse: Any) -> None:
        """Parse one SSE frame and dispatch it to the registered callback."""
        if sse.event == "heartbeat":
            return

        try:
            raw = json.loads(sse.data)
        except json.JSONDecodeError:
            logger.warning(
                "autoplay_sdk: could not parse event data: %s",
                sse.data[:200],
                exc_info=True,
                extra={"url": self._url},
            )
            return

        event_type = raw.get("type")

        try:
            if event_type == "actions":
                typed: ActionsPayload | SummaryPayload = ActionsPayload.from_dict(raw)
            elif event_type == "summary":
                typed = SummaryPayload.from_dict(raw)
            else:
                logger.debug(
                    "autoplay_sdk: unknown event type: %s",
                    event_type,
                    extra={"event_type": event_type, "url": self._url},
                )
                return
        except Exception as exc:
            logger.error(
                "autoplay_sdk: failed to deserialize event_type=%s — skipping: %s",
                event_type,
                exc,
                exc_info=True,
                extra={"event_type": event_type, "url": self._url},
            )
            return

        session_id = getattr(typed, "session_id", None) or "_nosession"
        await self._dispatch(session_id, typed)

    async def _dispatch(
        self, session_id: str, typed: ActionsPayload | SummaryPayload
    ) -> None:
        """Invoke the registered callback under the per-session semaphore."""
        sem = self._session_semaphores.get(session_id)
        if sem is None:
            sem = asyncio.Semaphore(self._session_concurrency)
            self._session_semaphores[session_id] = sem
            if len(self._session_semaphores) > _MAX_SESSION_SEMAPHORES:
                self._session_semaphores.popitem(last=False)
        else:
            self._session_semaphores.move_to_end(session_id)

        cb: ActionCallback | SummaryCallback | None
        if isinstance(typed, ActionsPayload):
            cb = self._actions_cb
            event_type = "actions"
        else:
            cb = self._summary_cb
            event_type = "summary"

        if cb is None:
            return

        product_id = getattr(typed, "product_id", None)

        # Drop and record if all concurrency slots for this session are busy.
        if sem.locked():
            logger.debug(
                "autoplay_sdk: session semaphore full — dropping event "
                "(event_type=%s, session=%s)",
                event_type,
                session_id,
                extra={
                    "event_type": event_type,
                    "session_id": session_id,
                    "product_id": product_id,
                    "url": self._url,
                },
            )
            _safe_call(
                self._metrics,
                "record_event_dropped",
                reason="queue_full",
                event_type=event_type,
                session_id=session_id,
                product_id=product_id,
            )
            return

        async with sem:
            self._active_dispatches += 1
            _safe_call(
                self._metrics,
                "record_queue_depth",
                depth=self._active_dispatches,
            )
            try:
                result = cb(typed)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: callback raised an error for event_type=%s session=%s: %s",
                    event_type,
                    session_id,
                    exc,
                    exc_info=True,
                    extra={
                        "event_type": event_type,
                        "session_id": session_id,
                        "product_id": product_id,
                        "url": self._url,
                    },
                )
            finally:
                self._active_dispatches -= 1
