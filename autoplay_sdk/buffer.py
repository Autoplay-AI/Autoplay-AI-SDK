"""autoplay_sdk.buffer — Pull-based event buffer.

Collects incoming real-time events so you can read them at any time rather
than having to process them immediately in a callback.

Two implementations are provided:

``EventBuffer`` (default, in-memory)
    Thread-safe ``deque`` behind a ``threading.Lock``.  Suitable for
    development, testing, and low-to-medium traffic deployments where a
    single process is acceptable.  Works with both ``ConnectorClient`` and
    ``AsyncConnectorClient``.

``RedisEventBuffer`` (production, async)
    Mirrors the event connector's ``storage/event_buffer.py`` architecture:
    one Redis ZSET per session, score = Unix timestamp,
    ``ZREMRANGEBYSCORE`` sliding-window trim on every write,
    ``asyncio.Semaphore`` backpressure with a 0.1 s timeout (drops rather
    than queuing unboundedly), and graceful degradation to no-op when Redis
    is unavailable.  Designed for high-throughput, multi-process, or
    multi-pod deployments.  Use with ``AsyncConnectorClient`` only.

``BufferBackend`` (protocol)
    Implement this to plug in any durable store (Kafka, Postgres, etc.)
    as the backing store for async event buffering.

Usage (in-memory, dev)::

    from autoplay_sdk import ConnectorClient, EventBuffer

    buffer = EventBuffer(max_size=1000)
    client = ConnectorClient(url=URL, token=TOKEN)
    client.on_actions(buffer.add).on_summary(buffer.add)
    client.run_in_background()

    events = buffer.drain()   # returns all events and clears the buffer

Usage (Redis, production)::

    from autoplay_sdk import AsyncConnectorClient
    from autoplay_sdk.buffer import RedisEventBuffer

    buffer = RedisEventBuffer(redis_url="redis://localhost:6379/0")
    client = AsyncConnectorClient(url=URL, token=TOKEN)
    client.on_actions(buffer.add).on_summary(buffer.add)
    await client.run()

    events = await buffer.drain()

Fire-and-forget pattern (when you don't want ``buffer.add`` to be awaited
inline during dispatch — useful when the semaphore on ``buffer.add`` would
otherwise serialize event handling)::

    import asyncio

    client.on_actions(lambda p: asyncio.create_task(buffer.add(p)))
    client.on_summary(lambda p: asyncio.create_task(buffer.add(p)))
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from autoplay_sdk.metrics import SdkMetricsHook, _safe_call
from autoplay_sdk.models import ActionsPayload, AnyPayload, SummaryPayload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BufferBackend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BufferBackend(Protocol):
    """Async storage backend protocol for pluggable event buffering.

    Implement this to use any durable store (Redis, Postgres, Kafka, etc.)
    as the backing store behind an async event buffer.

    All methods are coroutines so implementations may perform async I/O
    without blocking the event loop.
    """

    async def add(self, payload: AnyPayload) -> None:
        """Persist a payload to the backend store."""
        ...

    async def drain(self) -> list[AnyPayload]:
        """Return all stored payloads and clear the store."""
        ...

    async def size(self) -> int:
        """Return the number of payloads currently stored."""
        ...


# ---------------------------------------------------------------------------
# Serialization helpers for RedisEventBuffer
# ---------------------------------------------------------------------------


def _payload_to_json(payload: AnyPayload) -> str:
    """Serialize a typed payload to a compact JSON string for Redis storage."""
    if isinstance(payload, ActionsPayload):
        return json.dumps(
            {
                "type": "actions",
                "product_id": payload.product_id,
                "session_id": payload.session_id,
                "user_id": payload.user_id,
                "email": payload.email,
                "actions": [
                    {
                        "title": a.title,
                        "description": a.description,
                        "canonical_url": a.canonical_url,
                        "index": a.index,
                        "type": a.type,
                        "timestamp_start": a.timestamp_start,
                        "timestamp_end": a.timestamp_end,
                        "raw_url": a.raw_url,
                        "session_id": a.session_id,
                        "user_id": a.user_id,
                        "email": a.email,
                    }
                    for a in payload.actions
                ],
                "count": payload.count,
                "forwarded_at": payload.forwarded_at,
            },
            separators=(",", ":"),
        )
    return json.dumps(
        {
            "type": "summary",
            "product_id": payload.product_id,
            "session_id": payload.session_id,
            "summary": payload.summary,
            "replaces": payload.replaces,
            "forwarded_at": payload.forwarded_at,
        },
        separators=(",", ":"),
    )


def _payload_from_json(raw: str) -> AnyPayload | None:
    """Deserialize a JSON string back into a typed payload. Returns None on error.

    Handles the optional unique-ID prefix added to prevent ZSET member collisions.
    Format with prefix: ``"<8-hex>:<json>"`` — backward-compatible when absent.
    """
    # Strip optional collision-prevention prefix (8 hex chars + colon = 9 chars).
    if len(raw) > 9 and raw[8] == ":":
        raw = raw[9:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "autoplay_sdk: RedisEventBuffer corrupt JSON in drain — skipping entry",
            exc_info=True,
            extra={"raw_snippet": raw[:200] if raw else None},
        )
        return None
    event_type = data.get("type")
    try:
        if event_type == "actions":
            return ActionsPayload.from_dict(data)
        if event_type == "summary":
            return SummaryPayload.from_dict(data)
    except Exception:
        logger.warning(
            "autoplay_sdk: RedisEventBuffer could not deserialize %s payload in drain — skipping",
            event_type,
            exc_info=True,
            extra={"event_type": event_type},
        )
        return None
    return None


# ---------------------------------------------------------------------------
# EventBuffer — in-memory, sync, dev default
# ---------------------------------------------------------------------------


class EventBuffer:
    """Thread-safe in-memory buffer for real-time events.

    Stores incoming ``ActionsPayload`` and ``SummaryPayload`` objects as they
    arrive.  When the buffer is full (``max_size`` reached), the **oldest**
    event is silently dropped to make room for the new one and ``on_drop``
    is called if registered.

    Args:
        max_size: Maximum number of events to keep in memory.  Defaults to
                  1000.  Set to ``0`` for unlimited (not recommended in
                  production — use ``RedisEventBuffer`` instead).
        on_drop:  Optional ``(payload: AnyPayload) -> None`` called whenever
                  an event is dropped due to a full buffer.  Use this for
                  metrics or alerting.
    """

    def __init__(
        self,
        max_size: int = 1000,
        on_drop: Callable[[AnyPayload], None] | None = None,
    ) -> None:
        if max_size < 0:
            raise ValueError(f"max_size must be >= 0 (0 = unlimited), got {max_size!r}")
        self._max_size = max_size
        self._buf: deque[AnyPayload] = deque(maxlen=max_size if max_size > 0 else None)
        self._lock = threading.Lock()
        self._on_drop = on_drop

    # ------------------------------------------------------------------
    # Write side (called by the SDK client)
    # ------------------------------------------------------------------

    def add(self, payload: AnyPayload) -> None:
        """Add an event to the buffer.

        Wire this directly to ``on_actions`` or ``on_summary``::

            client.on_actions(buffer.add).on_summary(buffer.add)

        When the buffer is full the oldest event is dropped automatically
        and ``on_drop`` is called if registered.

        Args:
            payload: A typed ``ActionsPayload`` or ``SummaryPayload`` instance.
        """
        with self._lock:
            if self._max_size > 0 and len(self._buf) >= self._max_size:
                dropped = self._buf[0]
                logger.warning(
                    "autoplay_sdk: EventBuffer full (max_size=%d) — dropping %s session=%s",
                    self._max_size,
                    type(dropped).__name__,
                    getattr(dropped, "session_id", None),
                    extra={
                        "session_id": getattr(dropped, "session_id", None),
                        "product_id": getattr(dropped, "product_id", None),
                    },
                )
                if self._on_drop is not None:
                    try:
                        self._on_drop(dropped)
                    except Exception:
                        logger.warning(
                            "autoplay_sdk: on_drop callback raised",
                            exc_info=True,
                            extra={
                                "session_id": getattr(dropped, "session_id", None),
                                "product_id": getattr(dropped, "product_id", None),
                            },
                        )
            self._buf.append(payload)

    # ------------------------------------------------------------------
    # Read side (called by your application)
    # ------------------------------------------------------------------

    def drain(self) -> list[AnyPayload]:
        """Return all buffered events and clear the buffer.

        Use this when you want to process a batch of events — for example
        in a periodic task, a request handler, or a RAG indexing job.

        Returns:
            List of ``ActionsPayload`` / ``SummaryPayload`` objects in the
            order they were received.  Returns an empty list if there are
            no events.

        Example::

            events = buffer.drain()
            for payload in events:
                text = payload.to_text()
                embed_and_upsert(text, session_id=payload.session_id)
        """
        with self._lock:
            events = list(self._buf)
            self._buf.clear()
            return events

    def peek(self, n: int | None = None) -> list[AnyPayload]:
        """Return the most recent events without clearing the buffer.

        Args:
            n: Number of most recent events to return.  ``None`` returns all.

        Returns:
            List of events (oldest first within the slice).

        Example::

            # Log the last 5 events for debugging
            for p in buffer.peek(n=5):
                print(p.to_text())
        """
        with self._lock:
            events = list(self._buf)
        if n is None:
            return events
        if n == 0:
            return []
        return events[-n:]

    def drain_by_type(
        self,
        *,
        actions: bool = True,
        summaries: bool = True,
    ) -> list[AnyPayload]:
        """Drain only specific event types and leave others in the buffer.

        Useful when your actions processor and your summary processor run
        at different cadences.

        Args:
            actions:   Include ``ActionsPayload`` events.  Default ``True``.
            summaries: Include ``SummaryPayload`` events.  Default ``True``.

        Returns:
            Matching events in arrival order.  Unmatched events remain buffered.

        Example::

            # Process only summaries in this batch
            summaries = buffer.drain_by_type(actions=False, summaries=True)
        """
        with self._lock:
            keep: deque[AnyPayload] = deque(
                maxlen=self._max_size if self._max_size > 0 else None
            )
            result: list[AnyPayload] = []
            for event in self._buf:
                is_actions = isinstance(event, ActionsPayload)
                is_summary = isinstance(event, SummaryPayload)
                if (is_actions and actions) or (is_summary and summaries):
                    result.append(event)
                else:
                    keep.append(event)
            self._buf = keep
        return result

    def clear(self) -> None:
        """Discard all buffered events without returning them."""
        with self._lock:
            self._buf.clear()

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of events currently in the buffer."""
        with self._lock:
            return len(self._buf)

    @property
    def is_empty(self) -> bool:
        """``True`` when there are no buffered events."""
        return self.size == 0

    @property
    def max_size(self) -> int:
        """Maximum buffer capacity (0 = unlimited)."""
        return self._max_size

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"EventBuffer(size={self.size}, max_size={self._max_size})"


# ---------------------------------------------------------------------------
# RedisEventBuffer — async, Redis ZSET sliding window, production
# ---------------------------------------------------------------------------

_SESSIONS_KEY = "autoplay:sdk:sessions:{prefix}"
_BUFFER_KEY = "autoplay:sdk:buffer:{prefix}:{session_id}"
_DEFAULT_WINDOW_S = 120.0  # 2-minute sliding window, matching the event connector


class RedisEventBuffer:
    """Production Redis-backed event buffer for high-throughput deployments.

    Mirrors the event connector's ``storage/event_buffer.py`` architecture:

    - One Redis ZSET per session keyed by ``session_id``.
    - Score = ``forwarded_at`` Unix timestamp — enables chronological ordering
      and ``ZREMRANGEBYSCORE`` sliding-window eviction on every write.
    - ``asyncio.Semaphore`` with a 0.1 s acquire timeout — drops the payload
      and calls ``on_drop`` instead of queuing unboundedly when Redis is slow.
    - Lazy connection with graceful degradation — if Redis is unavailable,
      ``add()`` calls ``on_drop`` and returns; ``drain()`` returns ``[]``.

    Implements the ``BufferBackend`` protocol.  Designed for use with
    ``AsyncConnectorClient`` only (all public methods are coroutines).

    Args:
        redis_url:       Redis connection URL (e.g. ``"redis://localhost:6379/0"``).
        key_prefix:      Namespace prefix for all Redis keys.  Use a unique value
                         per service / environment to avoid key collisions.
                         Default: ``"default"``.
        window_seconds:  Sliding window size.  Events older than this are
                         automatically evicted on the next write.
                         Default: ``120.0`` (2 minutes, matching the connector).
        max_concurrent:  Maximum number of concurrent Redis write operations
                         before backpressure kicks in.  Default: ``10``.
        on_drop:         Optional ``(payload: AnyPayload) -> None`` called when
                         a payload is dropped due to backpressure or Redis being
                         unavailable.  Use for metrics or alerting.
        metrics:         Optional ``SdkMetricsHook`` implementation.  Receives
                         Redis operation latencies and semaphore-timeout counters.
                         See ``autoplay_sdk.metrics`` for the full interface.

    Example::

        from autoplay_sdk import AsyncConnectorClient
        from autoplay_sdk.buffer import RedisEventBuffer

        dropped: list = []

        buffer = RedisEventBuffer(
            redis_url="redis://localhost:6379/0",
            key_prefix="my_service",
            on_drop=lambda p: dropped.append(p),
        )

        client = AsyncConnectorClient(url=URL, token=TOKEN)
        client.on_actions(buffer.add).on_summary(buffer.add)
        task = client.run_in_background()

        await asyncio.sleep(60)

        events = await buffer.drain()   # typed list, chronological order
        client.stop()
        await task
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "default",
        window_seconds: float = _DEFAULT_WINDOW_S,
        max_concurrent: int = 10,
        on_drop: Callable[[AnyPayload], None] | None = None,
        metrics: SdkMetricsHook | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._prefix = key_prefix
        self._window_s = window_seconds
        self._max_concurrent = max_concurrent
        self._on_drop = on_drop
        self._metrics = metrics

        self._redis: Any = None
        self._available: bool | None = None
        # Unix timestamp after which a failed connection should be retried.
        self._retry_after: float = 0.0
        # Serialises concurrent callers during lazy initialisation so only one
        # connection pool is ever created (double-checked locking pattern).
        self._init_lock = asyncio.Lock()
        # Created lazily inside an async context so it belongs to the correct loop.
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    async def _get_redis(self) -> tuple[Any, bool]:
        # Fast path: already settled (connected or in cooldown).
        if self._available is True:
            return self._redis, True
        if self._available is False and time.time() < self._retry_after:
            return None, False

        # Slow path: first call or cooldown expired — serialise via lock.
        async with self._init_lock:
            # Double-check after acquiring: a racing caller may have settled first.
            if self._available is True:
                return self._redis, True
            if self._available is False and time.time() < self._retry_after:
                return None, False

            # Reset so the connect block always starts from a clean slate.
            self._available = None

            try:
                from redis.asyncio import ConnectionPool, Redis

                pool = ConnectionPool.from_url(
                    self._redis_url,
                    max_connections=self._max_concurrent + 2,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=True,
                )
                client = Redis(connection_pool=pool)
                await client.ping()
                self._redis = client
                self._available = True
                logger.info(
                    "autoplay_sdk: RedisEventBuffer connected to %s (prefix=%s)",
                    self._redis_url,
                    self._prefix,
                    extra={"redis_url": self._redis_url, "key_prefix": self._prefix},
                )
            except Exception as exc:
                logger.warning(
                    "autoplay_sdk: RedisEventBuffer Redis unavailable — on_drop will fire: %s",
                    exc,
                    exc_info=True,
                    extra={"redis_url": self._redis_url, "key_prefix": self._prefix},
                )
                self._available = False
                # Retry after 30 s so a transient Redis restart is recovered automatically.
                self._retry_after = time.time() + 30.0

        return self._redis, self._available

    def _call_on_drop(self, payload: AnyPayload) -> None:
        if self._on_drop is not None:
            try:
                self._on_drop(payload)
            except Exception:
                logger.warning(
                    "autoplay_sdk: on_drop callback raised",
                    exc_info=True,
                    extra={
                        "session_id": getattr(payload, "session_id", None),
                        "product_id": getattr(payload, "product_id", None),
                    },
                )

    # ------------------------------------------------------------------
    # BufferBackend protocol implementation
    # ------------------------------------------------------------------

    async def add(self, payload: AnyPayload) -> None:
        """Add a payload to the session's sliding-window ZSET.

        Trims entries older than ``window_seconds`` before adding, keeping
        the ZSET as a strict sliding window.  Intended to be wired directly
        to ``on_actions`` / ``on_summary`` callbacks::

            client.on_actions(buffer.add).on_summary(buffer.add)

        For fire-and-forget usage, wrap with ``asyncio.create_task()``::

            client.on_actions(lambda p: asyncio.create_task(buffer.add(p)))

        Args:
            payload: A typed ``ActionsPayload`` or ``SummaryPayload`` instance.
        """
        r, available = await self._get_redis()
        if not available or r is None:
            _safe_call(
                self._metrics,
                "record_event_dropped",
                reason="redis_unavailable",
                event_type="actions"
                if isinstance(payload, ActionsPayload)
                else "summary",
                session_id=getattr(payload, "session_id", None),
                product_id=getattr(payload, "product_id", None),
            )
            self._call_on_drop(payload)
            return

        try:
            await asyncio.wait_for(self._get_semaphore().acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            session_id_for_drop = getattr(payload, "session_id", None)
            product_id_for_drop = getattr(payload, "product_id", None)
            logger.warning(
                "autoplay_sdk: RedisEventBuffer semaphore full — dropping payload session=%s",
                session_id_for_drop or "unknown",
                extra={
                    "session_id": session_id_for_drop,
                    "product_id": product_id_for_drop,
                    "redis_url": self._redis_url,
                    "backpressure_reason": "semaphore_timeout",
                },
            )
            _safe_call(
                self._metrics,
                "record_semaphore_timeout",
                session_id=session_id_for_drop,
                product_id=product_id_for_drop,
            )
            _safe_call(
                self._metrics,
                "record_event_dropped",
                reason="semaphore_timeout",
                event_type="actions"
                if isinstance(payload, ActionsPayload)
                else "summary",
                session_id=session_id_for_drop,
                product_id=product_id_for_drop,
            )
            self._call_on_drop(payload)
            return

        session_id = getattr(payload, "session_id", None) or "_nosession"
        ts = payload.forwarded_at or time.time()
        sessions_key = _SESSIONS_KEY.format(prefix=self._prefix)
        buffer_key = _BUFFER_KEY.format(prefix=self._prefix, session_id=session_id)

        t0 = time.perf_counter()
        success = False
        try:
            pipe = r.pipeline()
            # Track active sessions so drain() can enumerate them.
            pipe.sadd(sessions_key, session_id)
            # Evict entries older than the sliding window.
            pipe.zremrangebyscore(buffer_key, "-inf", ts - self._window_s)
            # Store the serialized payload with forwarded_at as score.
            # Prefix with a short unique ID so identical payloads (replays,
            # duplicate forwards, zero-action batches) each get their own slot
            # instead of silently overwriting the score.
            member = f"{uuid.uuid4().hex[:8]}:{_payload_to_json(payload)}"
            pipe.zadd(buffer_key, {member: ts})
            await pipe.execute()
            success = True
        except Exception as exc:
            logger.warning(
                "autoplay_sdk: RedisEventBuffer.add failed for session=%s product=%s: %s",
                session_id,
                getattr(payload, "product_id", None),
                exc,
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "product_id": getattr(payload, "product_id", None),
                    "redis_url": self._redis_url,
                },
            )
            self._call_on_drop(payload)
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            _safe_call(
                self._metrics,
                "record_redis_operation",
                operation="add",
                elapsed_ms=elapsed_ms,
                success=success,
            )
            self._get_semaphore().release()

    async def drain(self) -> list[AnyPayload]:
        """Retrieve all buffered payloads across all sessions and clear the buffer.

        Uses an atomic pipeline per session (``ZRANGE`` + ``DELETE``).
        Returns payloads sorted chronologically by ``forwarded_at``.

        Returns:
            List of ``ActionsPayload`` / ``SummaryPayload`` objects, oldest
            first.  Returns an empty list if Redis is unavailable.

        Example::

            events = await buffer.drain()
            for payload in events:
                await embed_and_upsert(payload.to_text(), session_id=payload.session_id)
        """
        r, available = await self._get_redis()
        if not available or r is None:
            return []

        sessions_key = _SESSIONS_KEY.format(prefix=self._prefix)

        try:
            session_ids: set[str] = await r.smembers(sessions_key)
        except Exception as exc:
            logger.warning(
                "autoplay_sdk: RedisEventBuffer.drain could not fetch sessions: %s",
                exc,
                exc_info=True,
                extra={"redis_url": self._redis_url, "key_prefix": self._prefix},
            )
            return []

        if not session_ids:
            return []

        buffer_keys = [
            _BUFFER_KEY.format(prefix=self._prefix, session_id=sid)
            for sid in session_ids
        ]

        t0 = time.perf_counter()
        drain_success = False
        try:
            pipe = r.pipeline()
            for key in buffer_keys:
                # Fetch all members with their scores so we can sort globally.
                pipe.zrange(key, 0, -1, withscores=True)
            for key in buffer_keys:
                pipe.delete(key)
            pipe.delete(sessions_key)
            results = await pipe.execute()
            drain_success = True
        except Exception as exc:
            logger.warning(
                "autoplay_sdk: RedisEventBuffer.drain pipeline failed: %s",
                exc,
                exc_info=True,
                extra={"redis_url": self._redis_url, "key_prefix": self._prefix},
            )
            return []
        finally:
            _safe_call(
                self._metrics,
                "record_redis_operation",
                operation="drain",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                success=drain_success,
            )

        scored: list[tuple[float, AnyPayload]] = []
        for members_with_scores in results[: len(session_ids)]:
            for raw, score in members_with_scores:
                payload = _payload_from_json(raw)
                if payload is not None:
                    scored.append((score, payload))

        scored.sort(key=lambda x: x[0])
        return [p for _, p in scored]

    async def size(self) -> int:
        """Return the total number of buffered payloads across all sessions.

        Returns:
            Total event count, or ``0`` if Redis is unavailable.
        """
        r, available = await self._get_redis()
        if not available or r is None:
            return 0

        sessions_key = _SESSIONS_KEY.format(prefix=self._prefix)

        try:
            session_ids: set[str] = await r.smembers(sessions_key)
            if not session_ids:
                return 0
            pipe = r.pipeline()
            for sid in session_ids:
                pipe.zcard(_BUFFER_KEY.format(prefix=self._prefix, session_id=sid))
            counts = await pipe.execute()
            return sum(counts)
        except Exception as exc:
            logger.warning(
                "autoplay_sdk: RedisEventBuffer.size failed: %s",
                exc,
                exc_info=True,
                extra={"redis_url": self._redis_url, "key_prefix": self._prefix},
            )
            return 0

    def __repr__(self) -> str:
        return (
            f"RedisEventBuffer("
            f"prefix={self._prefix!r}, "
            f"window_seconds={self._window_s}, "
            f"available={self._available})"
        )
