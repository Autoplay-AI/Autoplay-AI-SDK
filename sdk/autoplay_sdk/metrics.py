"""autoplay_sdk.metrics — Pluggable metrics hook protocol.

Lets you wire Prometheus, Datadog, OpenTelemetry, or any other counters and
histograms into the SDK without modifying library code.  Implement only the
methods you care about — unimplemented methods are never called.

The ``SdkMetricsHook`` protocol uses ``@runtime_checkable`` so you can verify
conformance at startup with ``isinstance(obj, SdkMetricsHook)``.  Errors
raised inside any hook method are swallowed and logged at DEBUG so a broken
metrics implementation can never crash the event processing pipeline.

Currently wired call sites
--------------------------
The table below shows exactly which hook methods fire today, from where, and
when.  Methods that are defined in the protocol but not yet wired are noted
as "reserved for future use" — implement them now if you want them ready when
the SDK starts calling them.

+---------------------------+----------------------------------------------+------+
| Method                    | Caller                                       | When |
+===========================+==============================================+======+
| record_event_dropped      | ConnectorClient (_enqueue)                   | Event dropped because internal queue is full |
|                           | AsyncConnectorClient (_dispatch)             | Session semaphore at capacity and event is skipped |
|                           | AsyncSessionSummarizer (add)                 | Per-session queue full |
|                           | RedisEventBuffer (add)                       | Redis unavailable or semaphore timeout |
+---------------------------+----------------------------------------------+------+
| record_queue_depth        | ConnectorClient (_enqueue)                   | After every successfully enqueued event |
|                           | AsyncConnectorClient (_dispatch)             | After acquiring a session semaphore slot |
+---------------------------+----------------------------------------------+------+
| record_summarizer_latency | AsyncSessionSummarizer (_summarise)          | After each successful LLM summarization |
+---------------------------+----------------------------------------------+------+
| record_redis_operation    | RedisEventBuffer (add, drain)                | After each Redis pipeline execution |
+---------------------------+----------------------------------------------+------+
| record_semaphore_timeout  | RedisEventBuffer (add)                       | When the concurrency semaphore times out |
+---------------------------+----------------------------------------------+------+

Note: ``SessionSummarizer`` (sync) does not call any hook methods.

Usage::

    from autoplay_sdk import ConnectorClient
    from autoplay_sdk.metrics import SdkMetricsHook

    class MyMetrics:
        def record_event_dropped(self, *, reason, event_type, session_id, product_id):
            # reason is one of: "queue_full", "redis_unavailable", "semaphore_timeout"
            dropped_counter.labels(reason=reason, event_type=event_type).inc()

        def record_queue_depth(self, *, depth):
            queue_depth_gauge.set(depth)

        def record_summarizer_latency(self, *, session_id, elapsed_ms, action_count):
            summarizer_latency.observe(elapsed_ms / 1000)

        def record_redis_operation(self, *, operation, elapsed_ms, success):
            # operation is "add" or "drain"
            redis_latency.labels(op=operation, success=str(success)).observe(elapsed_ms / 1000)

        def record_semaphore_timeout(self, *, session_id, product_id):
            semaphore_timeout_counter.inc()

    # metrics is wired for ConnectorClient today
    client = ConnectorClient(url=URL, token=TOKEN, metrics=MyMetrics())

    # Pass to RedisEventBuffer for Redis and semaphore metrics
    from autoplay_sdk.buffer import RedisEventBuffer
    buffer = RedisEventBuffer(redis_url="redis://localhost:6379/0", metrics=MyMetrics())

    # Pass to AsyncSessionSummarizer for summarizer latency metrics
    from autoplay_sdk import AsyncSessionSummarizer
    summarizer = AsyncSessionSummarizer(llm=my_llm, metrics=MyMetrics())
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SdkMetricsHook(Protocol):
    """Protocol for plugging in custom metrics backends.

    All methods are keyword-only to allow future fields to be added without
    breaking existing implementations.  Implement only the methods relevant
    to your monitoring stack — unimplemented methods are never called.

    See the module docstring for a table of which methods are currently wired
    and which are reserved for future use.

    Methods
    -------
    record_event_dropped:
        **Currently wired** — called by ``ConnectorClient`` when an event is
        dropped due to a full internal queue, and by ``RedisEventBuffer`` when
        Redis is unavailable or the concurrency semaphore times out.

        ``reason`` is one of:
        - ``"queue_full"`` — the internal dispatch queue is saturated
        - ``"redis_unavailable"`` — Redis is down or unreachable
        - ``"semaphore_timeout"`` — Redis buffer concurrency limit exceeded

    record_queue_depth:
        **Currently wired** — called by ``ConnectorClient`` on every
        successfully enqueued event, reflecting queue depth immediately after
        the enqueue.  Also called by ``AsyncConnectorClient`` each time a
        session semaphore slot is successfully acquired, reflecting the total
        number of concurrently active dispatches across all sessions.

    record_summarizer_latency:
        **Currently wired** — called by ``AsyncSessionSummarizer`` after each
        successful LLM summarization call.  *Not* called by the sync
        ``SessionSummarizer``.

    record_redis_operation:
        **Currently wired** — called by ``RedisEventBuffer`` after every Redis
        pipeline execution.  ``operation`` is ``"add"`` or ``"drain"``.

    record_semaphore_timeout:
        **Currently wired** — called by ``RedisEventBuffer`` when a payload is
        dropped because the concurrency semaphore timed out (backpressure).
    """

    def record_event_dropped(
        self,
        *,
        reason: str,
        event_type: str,
        session_id: str | None,
        product_id: str | None,
    ) -> None:
        """Record a dropped event."""
        ...

    def record_summarizer_latency(
        self,
        *,
        session_id: str,
        elapsed_ms: float,
        action_count: int,
    ) -> None:
        """Record LLM summarization latency."""
        ...

    def record_redis_operation(
        self,
        *,
        operation: str,
        elapsed_ms: float,
        success: bool,
    ) -> None:
        """Record a Redis pipeline operation latency."""
        ...

    def record_queue_depth(self, *, depth: int) -> None:
        """Record the current internal queue depth after an enqueue."""
        ...

    def record_semaphore_timeout(
        self,
        *,
        session_id: str | None,
        product_id: str | None,
    ) -> None:
        """Record a Redis buffer semaphore timeout (backpressure drop)."""
        ...


def _safe_call(hook: SdkMetricsHook | None, method: str, **kwargs: object) -> None:
    """Call a metrics hook method, swallowing and logging any exceptions.

    Used internally by the SDK so a broken metrics implementation never
    crashes the event processing pipeline.
    """
    if hook is None:
        return
    fn = getattr(hook, method, None)
    if fn is None:
        return
    try:
        fn(**kwargs)
    except Exception as exc:
        logger.debug(
            "autoplay_sdk: metrics hook %s raised (ignored): %s",
            method,
            exc,
            exc_info=True,
        )
