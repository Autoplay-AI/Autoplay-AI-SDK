"""autoplay_sdk.client — ConnectorClient for the Autoplay real-time event stream.

Receives structured UI actions and LLM session summaries from the Autoplay
event connector in real-time via SSE (Server-Sent Events).

Quickstart::

    from autoplay_sdk import ConnectorClient, ActionsPayload

    def on_actions(payload: ActionsPayload):
        for action in payload.actions:
            print(action.title, action.canonical_url)

    ConnectorClient(url="https://host/stream/my_product", token="uk_live_...") \\
        .on_actions(on_actions) \\
        .run()

Background usage (non-blocking)::

    client = ConnectorClient(url="...", token="...").on_actions(on_actions)
    client.run_in_background()
    # your application continues here
    ...
    client.stop()

Context manager (clean shutdown for applications)::

    with ConnectorClient(url="...", token="...") as client:
        client.on_actions(on_actions).run_in_background()
        do_other_work()
    # stop() is called automatically on exit

High-volume / RAG usage
-----------------------
The client decouples the SSE receive loop from callback execution via an
internal ``queue.Queue``.  The receive thread reads events from the stream and
enqueues them; a separate worker thread drains the queue and calls your
callbacks.  Your callback can block (e.g. write to a vector store) without
ever stalling the stream reader.

If the queue fills up (``max_queue_size`` events are waiting), new events are
dropped, counted in ``dropped_count``, and passed to your ``on_drop`` callback
if one is registered.  Monitor ``dropped_count`` in production — a non-zero
value means your callback is slower than the incoming event rate.

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

Lifecycle hooks
---------------
Use ``on_connect`` and ``on_disconnect`` to react to connection events::

    def reset_state():
        context_store.reset_all()

    client = ConnectorClient(url="...", token="...", on_connect=reset_state)
"""

from __future__ import annotations

import json
import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from httpx_sse import connect_sse

from autoplay_sdk.exceptions import SdkUpstreamError
from autoplay_sdk.metrics import SdkMetricsHook, _safe_call
from autoplay_sdk.models import ActionsPayload, SummaryPayload
from autoplay_sdk.stream_auth import resolve_connector_bearer_token

logger = logging.getLogger(__name__)

_WORKER_STOP = object()  # sentinel that tells the worker thread to exit


class ConnectorClient:
    """Subscribes to an Autoplay connector SSE stream and dispatches events to callbacks.

    The SSE receive loop and the callback execution run on separate threads.
    This means slow callbacks (DB writes, vector store upserts, LLM calls, etc.)
    never block the stream reader — the stream stays open and events keep
    arriving regardless of how long your processing takes.

    Reconnect policy: exponential backoff starting at ``initial_backoff_s``
    (default 1 s), doubling each attempt up to ``max_backoff_s`` (default
    30 s), with ±10 % jitter.  HTTP 401/403/404 are immediately fatal.
    See the module docstring for the full contract.

    Args:
        url:               Full URL to ``GET /stream/{product_id}`` on the connector.
        token:             Unkey API key for this product (``uk_live_...``).
                           Created in the Unkey dashboard with ``external_id`` set
                           to the ``product_id``. If empty, uses environment variable
                           ``AUTOPLAY_APP_UNKEY_TOKEN`` (same token for stream events
                           including tour payloads after the Messenger proactive popup).
        max_queue_size:    Maximum number of events that can be buffered while the
                           worker thread is busy.  Events beyond this limit are
                           dropped and counted in ``dropped_count``.  Must be >= 1.
                           Default: 500.
        connect_timeout:   Seconds to wait for the initial TCP connection before
                           raising an error and triggering a reconnect.  Does not
                           limit how long the stream can stay open.  Default: 10.0.
        read_timeout_s:    Seconds to wait for data on an established connection
                           before raising a read timeout.  ``None`` (default) means
                           wait indefinitely — this is the correct value for SSE
                           streams where heartbeats may be infrequent.  Only set a
                           finite value if you know your server sends events or
                           heartbeats more frequently than this interval.
        initial_backoff_s: Seconds to wait before the first reconnect attempt.
                           Default: 1.0.
        max_backoff_s:     Upper bound on the reconnect wait (after exponential
                           growth).  Default: 30.0.
        max_retries:       Maximum number of reconnect attempts before giving up
                           and raising ``SdkUpstreamError``.  ``None`` retries
                           forever.  Default: ``None``.
        on_connect:        Optional ``() -> None`` called each time the SSE
                           connection is successfully established (including after
                           reconnects).  Useful for resetting state.
        on_disconnect:     Optional ``() -> None`` called each time the SSE
                           connection is lost (before the reconnect backoff sleep).
        metrics:           Optional ``SdkMetricsHook`` implementation.  Receives
                           counters for dropped events and queue depth.  See
                           ``autoplay_sdk.metrics`` for the full interface.
    """

    def __init__(
        self,
        url: str,
        token: str = "",
        max_queue_size: int = 500,
        connect_timeout: float = 10.0,
        read_timeout_s: float | None = None,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        max_retries: int | None = None,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        metrics: SdkMetricsHook | None = None,
    ) -> None:
        if max_queue_size < 1:
            raise ValueError(f"max_queue_size must be >= 1, got {max_queue_size!r}")
        if connect_timeout <= 0:
            raise ValueError(f"connect_timeout must be > 0, got {connect_timeout!r}")
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
        self._read_timeout_s = read_timeout_s
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._max_retries = max_retries
        self._on_connect_cb = on_connect
        self._on_disconnect_cb = on_disconnect
        self._metrics = metrics
        self._actions_cb: Callable[[ActionsPayload], None] | None = None
        self._summary_cb: Callable[[SummaryPayload], None] | None = None
        self._drop_cb: Callable[[dict, int], None] | None = None
        self._running = False
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._dropped = 0

    # ------------------------------------------------------------------
    # Builder interface
    # ------------------------------------------------------------------

    def on_actions(self, fn: Callable[[ActionsPayload], None]) -> "ConnectorClient":
        """Register a callback for ``actions`` events.

        Called every time the connector extracts a batch of UI actions from a
        user session.  Runs on a dedicated worker thread so blocking I/O (e.g.
        vector store upserts) is safe here.

        Args:
            fn: Callable that receives a typed ``ActionsPayload``.
                Call ``payload.to_text()`` to get an embedding-ready string.

        Returns:
            self — for method chaining.
        """
        self._actions_cb = fn
        return self

    def on_summary(self, fn: Callable[[SummaryPayload], None]) -> "ConnectorClient":
        """Register a callback for ``summary`` events.

        Called when the connector's LLM summariser produces a prose summary
        of a session, replacing the raw action history.  Useful for keeping
        a compact, up-to-date context window in your RAG pipeline.

        Args:
            fn: Callable that receives a typed ``SummaryPayload``.
                Call ``payload.to_text()`` to get the prose summary string.

        Returns:
            self — for method chaining.
        """
        self._summary_cb = fn
        return self

    def on_drop(self, fn: Callable[[dict, int], None]) -> "ConnectorClient":
        """Register a callback invoked when an event is dropped due to a full queue.

        Use this to alert, log to an external system, or increment a metric.

        Args:
            fn: Called with ``(payload, total_dropped)`` where ``payload`` is
                the dropped event dict and ``total_dropped`` is the running
                drop count including this event.

        Returns:
            self — for method chaining.
        """
        self._drop_cb = fn
        return self

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def dropped_count(self) -> int:
        """Number of events dropped because the internal queue was full.

        A non-zero value means your callback is slower than the incoming event
        rate.  Consider optimising the callback or increasing ``max_queue_size``.
        """
        return self._dropped

    @property
    def queue_size(self) -> int:
        """Number of events currently waiting in the internal queue.

        Use this for periodic health logging or dashboards.  A value that grows
        steadily over time indicates the worker thread cannot keep up.
        """
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Connect to the SSE stream and block until stopped or interrupted.

        Starts a background worker thread that drains the internal queue and
        calls your registered callbacks.  The SSE receive loop runs on the
        calling thread.

        Reconnects automatically with exponential backoff.  See the class
        docstring for the full reconnect policy.  Raises ``RuntimeError`` if
        ``max_retries`` is set and exhausted.
        """
        self._running = True
        worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="autoplay-sdk-worker"
        )
        worker.start()

        backoff = self._initial_backoff_s
        retry_count = 0
        headers = {"Accept": "text/event-stream"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        timeout = httpx.Timeout(
            connect=self._connect_timeout,
            read=self._read_timeout_s,  # None = stream indefinitely (correct for SSE)
            write=None,
            pool=None,
        )

        try:
            while self._running:
                try:
                    logger.info(
                        "autoplay_sdk: connecting to %s",
                        self._url,
                        extra={"url": self._url},
                    )
                    with httpx.Client(timeout=timeout) as client:
                        with connect_sse(
                            client, "GET", self._url, headers=headers
                        ) as source:
                            logger.info(
                                "autoplay_sdk: connected",
                                extra={"url": self._url},
                            )
                            backoff = self._initial_backoff_s
                            retry_count = 0
                            self._fire_on_connect()
                            for sse in source.iter_sse():
                                if not self._running:
                                    break
                                self._enqueue(sse)

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
                    self._fire_on_disconnect()
                except KeyboardInterrupt:
                    logger.info("autoplay_sdk: interrupted", extra={"url": self._url})
                    self._running = False
                    break
                except Exception as exc:
                    retry_count += 1
                    logger.warning(
                        "autoplay_sdk: connection lost (%s) — retrying in %.0fs (attempt %d)",
                        exc,
                        backoff,
                        retry_count,
                        extra={"url": self._url, "retry_count": retry_count},
                    )
                    self._fire_on_disconnect()

                if self._running:
                    if (
                        self._max_retries is not None
                        and retry_count > self._max_retries
                    ):
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
                    time.sleep(backoff + jitter)
                    backoff = min(backoff * 2, self._max_backoff_s)
        finally:
            # Signal the worker thread to drain remaining events and exit.
            self._queue.put(_WORKER_STOP)
            worker.join(timeout=10)
            if worker.is_alive():
                logger.warning(
                    "autoplay_sdk: worker thread did not stop within 10 s",
                    extra={"url": self._url},
                )
            logger.info("autoplay_sdk: stopped", extra={"url": self._url})

    def run_in_background(self) -> threading.Thread:
        """Start the SSE connection in a background daemon thread.

        Returns immediately so your application can continue running.  Call
        ``stop()`` to shut down cleanly when you are done.

        Returns:
            The daemon ``Thread`` running ``run()``.  You can ``join()`` it if
            you need to wait for a clean shutdown.

        Example::

            client = ConnectorClient(url="...", token="...").on_actions(fn)
            client.run_in_background()
            # application continues; events arrive in the background
            ...
            client.stop()
        """
        t = threading.Thread(target=self.run, daemon=True, name="autoplay-sdk-main")
        t.start()
        return t

    def stop(self) -> None:
        """Signal the client to stop after the current event is processed.

        Sets an internal flag that causes the SSE reader loop to exit cleanly
        after its current iteration.  The worker thread drains any remaining
        queued events before exiting.  Safe to call from any thread.

        If you used ``run_in_background()``, you can ``join()`` the returned
        thread after calling ``stop()`` to wait for a clean shutdown.
        """
        self._running = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ConnectorClient":
        """Support ``with ConnectorClient(...) as client:`` usage."""
        return self

    def __exit__(self, *_: Any) -> None:
        """Call ``stop()`` automatically when exiting the ``with`` block."""
        self.stop()

    def __repr__(self) -> str:
        return (
            f"ConnectorClient(url={self._url!r}, running={self._running}, "
            f"dropped={self._dropped})"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fire_on_connect(self) -> None:
        if self._on_connect_cb is not None:
            try:
                self._on_connect_cb()
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: on_connect callback raised: %s",
                    exc,
                    exc_info=True,
                    extra={"url": self._url},
                )

    def _fire_on_disconnect(self) -> None:
        if self._on_disconnect_cb is not None:
            try:
                self._on_disconnect_cb()
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: on_disconnect callback raised: %s",
                    exc,
                    exc_info=True,
                    extra={"url": self._url},
                )

    def _enqueue(self, sse: Any) -> None:
        """Parse an SSE frame and place the payload on the internal queue."""
        if sse.event == "heartbeat":
            return

        try:
            payload = json.loads(sse.data)
        except json.JSONDecodeError:
            logger.warning(
                "autoplay_sdk: could not parse event data: %s",
                sse.data[:200],
                exc_info=True,
                extra={"url": self._url},
            )
            return

        event_type = payload.get("type")
        if event_type not in ("actions", "summary"):
            logger.debug(
                "autoplay_sdk: unknown event type: %s",
                event_type,
                extra={"event_type": event_type, "url": self._url},
            )
            return

        try:
            self._queue.put_nowait(payload)
            _safe_call(
                self._metrics,
                "record_queue_depth",
                depth=self._queue.qsize(),
            )
        except queue.Full:
            self._dropped += 1
            session_id = payload.get("session_id")
            product_id = payload.get("product_id")
            logger.warning(
                "autoplay_sdk: queue full — dropping event (type=%s, session=%s, total_dropped=%d)",
                event_type,
                session_id,
                self._dropped,
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
                event_type=event_type or "",
                session_id=session_id,
                product_id=product_id,
            )
            if self._drop_cb is not None:
                try:
                    self._drop_cb(payload, self._dropped)
                except Exception as exc:
                    logger.error(
                        "autoplay_sdk: on_drop callback raised: %s",
                        exc,
                        exc_info=True,
                        extra={
                            "event_type": event_type,
                            "session_id": session_id,
                            "url": self._url,
                        },
                    )

    def _worker_loop(self) -> None:
        """Drain the internal queue and call the registered callbacks."""
        while True:
            item = self._queue.get()
            if item is _WORKER_STOP:
                self._queue.task_done()
                break
            try:
                self._dispatch(item)
            finally:
                self._queue.task_done()

    def _dispatch(self, payload: dict) -> None:
        """Parse a raw payload dict into a typed model and call the registered callback."""
        event_type = payload.get("type")

        try:
            if event_type == "actions":
                cb = self._actions_cb
                typed: ActionsPayload | SummaryPayload = ActionsPayload.from_dict(
                    payload
                )
            elif event_type == "summary":
                cb = self._summary_cb
                typed = SummaryPayload.from_dict(payload)
            else:
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

        if cb is None:
            return

        session_id = getattr(typed, "session_id", None) or "_nosession"
        product_id = getattr(typed, "product_id", None)
        try:
            cb(typed)
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
