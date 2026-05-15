"""Tests for autoplay_sdk.buffer.RedisEventBuffer — Redis-backed async buffer.

All Redis I/O is mocked so no real Redis server is required.  Tests inject
a mock Redis client directly into the buffer's internal state, bypassing the
lazy connection logic in ``_get_redis()``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoplay_sdk.buffer import BufferBackend, RedisEventBuffer, _payload_to_json
from autoplay_sdk.metrics import SdkMetricsHook
from autoplay_sdk.models import ActionsPayload, SlimAction, SummaryPayload

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _actions(session_id: str = "s1", ts: float = 1.0) -> ActionsPayload:
    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id=None,
        email=None,
        actions=[],
        count=0,
        forwarded_at=ts,
    )


def _summary(session_id: str = "s1", ts: float = 2.0) -> SummaryPayload:
    return SummaryPayload(
        product_id="p1",
        session_id=session_id,
        summary="Summary text",
        replaces=3,
        forwarded_at=ts,
    )


def _make_pipe() -> AsyncMock:
    """Return a minimal pipeline mock whose execute() returns [] by default."""
    pipe = AsyncMock()
    # Pipeline command methods return the pipe itself to support call chaining.
    for method in ("sadd", "zremrangebyscore", "zadd", "zrange", "delete", "zcard"):
        setattr(pipe, method, MagicMock(return_value=pipe))
    pipe.execute = AsyncMock(return_value=[])
    return pipe


def _make_redis(pipe: AsyncMock | None = None) -> MagicMock:
    """Return a minimal async Redis mock."""
    if pipe is None:
        pipe = _make_pipe()
    r = MagicMock()
    r.pipeline = MagicMock(return_value=pipe)
    r.smembers = AsyncMock(return_value=set())
    return r


def _inject_redis(buf: RedisEventBuffer, r: MagicMock) -> None:
    """Bypass _get_redis() by injecting a pre-made mock client."""
    buf._redis = r
    buf._available = True
    # Create the semaphore synchronously in the default event loop context.
    buf._semaphore = asyncio.Semaphore(buf._max_concurrent)


# ---------------------------------------------------------------------------
# BufferBackend protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_redis_buffer_satisfies_buffer_backend_protocol(self):
        buf = RedisEventBuffer("redis://localhost:6379")
        assert isinstance(buf, BufferBackend)


# ---------------------------------------------------------------------------
# Unavailable degradation
# ---------------------------------------------------------------------------


class TestUnavailableDegradation:
    @pytest.mark.asyncio
    async def test_add_calls_on_drop_when_unavailable(self):
        dropped: list = []
        buf = RedisEventBuffer("redis://localhost:9999", on_drop=dropped.append)
        buf._available = False

        await buf.add(_actions())
        assert len(dropped) == 1
        assert dropped[0].session_id == "s1"

    @pytest.mark.asyncio
    async def test_drain_returns_empty_when_unavailable(self):
        buf = RedisEventBuffer("redis://localhost:9999")
        buf._available = False
        assert await buf.drain() == []

    @pytest.mark.asyncio
    async def test_size_returns_zero_when_unavailable(self):
        buf = RedisEventBuffer("redis://localhost:9999")
        buf._available = False
        assert await buf.size() == 0

    @pytest.mark.asyncio
    async def test_connection_failure_marks_unavailable_and_fires_on_drop(self):
        """When the Redis connection attempt raises, _available becomes False."""
        dropped: list = []
        buf = RedisEventBuffer("redis://localhost:9999", on_drop=dropped.append)

        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            # Simulate redis not installed / unavailable
            await buf.add(_actions())

        assert buf._available is False
        assert len(dropped) == 1


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------


class TestAdd:
    @pytest.mark.asyncio
    async def test_add_executes_redis_pipeline(self):
        pipe = _make_pipe()
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="test")
        _inject_redis(buf, r)

        await buf.add(_actions("s1", ts=100.0))
        pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_registers_session_in_sessions_set(self):
        pipe = _make_pipe()
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="myapp")
        _inject_redis(buf, r)

        await buf.add(_actions("s1"))
        pipe.sadd.assert_called_once()
        sessions_key = pipe.sadd.call_args[0][0]
        assert "myapp" in sessions_key

    @pytest.mark.asyncio
    async def test_add_does_not_fire_on_drop_on_success(self):
        dropped: list = []
        pipe = _make_pipe()
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", on_drop=dropped.append)
        _inject_redis(buf, r)

        await buf.add(_actions())
        assert dropped == []

    @pytest.mark.asyncio
    async def test_add_fires_on_drop_on_pipeline_failure(self):
        dropped: list = []
        pipe = _make_pipe()
        pipe.execute = AsyncMock(side_effect=Exception("redis timeout"))
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", on_drop=dropped.append)
        _inject_redis(buf, r)

        await buf.add(_actions())
        assert len(dropped) == 1

    @pytest.mark.asyncio
    async def test_add_releases_semaphore_even_on_pipeline_failure(self):
        """The semaphore must be released in the finally block after a failure."""
        pipe = _make_pipe()
        pipe.execute = AsyncMock(side_effect=Exception("error"))
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", max_concurrent=2)
        _inject_redis(buf, r)

        await buf.add(_actions())
        # If the semaphore is released, we can acquire it again immediately.
        assert buf._semaphore._value == 2

    @pytest.mark.asyncio
    async def test_add_both_payload_types_are_accepted(self):
        pipe = _make_pipe()
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        await buf.add(_actions())
        await buf.add(_summary())
        assert pipe.execute.await_count == 2


# ---------------------------------------------------------------------------
# drain()
# ---------------------------------------------------------------------------


class TestDrain:
    @pytest.mark.asyncio
    async def test_drain_returns_empty_when_no_sessions(self):
        r = _make_redis()
        r.smembers = AsyncMock(return_value=set())
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="test")
        _inject_redis(buf, r)

        assert await buf.drain() == []

    @pytest.mark.asyncio
    async def test_drain_returns_payloads_sorted_by_timestamp(self):
        pipe = _make_pipe()
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="test")
        _inject_redis(buf, r)

        p_early = _actions("s1", ts=1.0)
        p_late = _actions("s2", ts=2.0)
        # smembers returns two sessions
        r.smembers = AsyncMock(return_value={"s1", "s2"})
        # pipeline results: 2 zrange results + 2 deletes + 1 sessions-key delete
        pipe.execute = AsyncMock(
            return_value=[
                [(_payload_to_json(p_early), 1.0)],
                [(_payload_to_json(p_late), 2.0)],
                1,
                1,
                1,
            ]
        )

        result = await buf.drain()
        assert len(result) == 2
        assert result[0].forwarded_at == 1.0
        assert result[1].forwarded_at == 2.0

    @pytest.mark.asyncio
    async def test_drain_returns_empty_on_smembers_failure(self):
        r = _make_redis()
        r.smembers = AsyncMock(side_effect=Exception("network error"))
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        assert await buf.drain() == []

    @pytest.mark.asyncio
    async def test_drain_returns_empty_on_pipeline_failure(self):
        pipe = _make_pipe()
        pipe.execute = AsyncMock(side_effect=Exception("pipeline failed"))
        r = _make_redis(pipe)
        r.smembers = AsyncMock(return_value={"s1"})
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        assert await buf.drain() == []

    @pytest.mark.asyncio
    async def test_drain_skips_corrupt_json_entries(self):
        pipe = _make_pipe()
        r = _make_redis(pipe)
        r.smembers = AsyncMock(return_value={"s1"})
        # One corrupt entry and one valid entry
        valid = _actions("s1", ts=5.0)
        pipe.execute = AsyncMock(
            return_value=[
                [("not-valid-json", 4.0), (_payload_to_json(valid), 5.0)],
                1,
                1,
            ]
        )
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        result = await buf.drain()
        assert len(result) == 1
        assert result[0].forwarded_at == 5.0


# ---------------------------------------------------------------------------
# size()
# ---------------------------------------------------------------------------


class TestSize:
    @pytest.mark.asyncio
    async def test_size_sums_zcard_across_sessions(self):
        pipe = _make_pipe()
        pipe.execute = AsyncMock(return_value=[3, 2])
        r = _make_redis(pipe)
        r.smembers = AsyncMock(return_value={"s1", "s2"})
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="test")
        _inject_redis(buf, r)

        total = await buf.size()
        assert total == 5

    @pytest.mark.asyncio
    async def test_size_returns_zero_when_no_sessions(self):
        r = _make_redis()
        r.smembers = AsyncMock(return_value=set())
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        assert await buf.size() == 0

    @pytest.mark.asyncio
    async def test_size_returns_zero_on_exception(self):
        r = _make_redis()
        r.smembers = AsyncMock(side_effect=Exception("redis error"))
        buf = RedisEventBuffer("redis://localhost:6379")
        _inject_redis(buf, r)

        assert await buf.size() == 0


# ---------------------------------------------------------------------------
# on_drop callback
# ---------------------------------------------------------------------------


class TestOnDrop:
    @pytest.mark.asyncio
    async def test_on_drop_receives_the_dropped_payload(self):
        dropped: list = []
        # Use port 9999 — guaranteed no Redis there, so _get_redis() fails and
        # on_drop is called reliably even if a real Redis runs on 6379.
        buf = RedisEventBuffer("redis://localhost:9999", on_drop=dropped.append)
        buf._available = False

        p = _actions("s1")
        await buf.add(p)
        assert dropped == [p]

    @pytest.mark.asyncio
    async def test_on_drop_raising_does_not_propagate(self):
        """Errors inside the on_drop callback must be swallowed."""

        def bad_drop(p):
            raise RuntimeError("drop handler failed")

        buf = RedisEventBuffer("redis://localhost:6379", on_drop=bad_drop)
        buf._available = False

        await buf.add(_actions())  # must not raise

    @pytest.mark.asyncio
    async def test_on_drop_called_once_per_dropped_payload(self):
        dropped: list = []
        pipe = _make_pipe()
        pipe.execute = AsyncMock(side_effect=Exception("error"))
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", on_drop=dropped.append)
        _inject_redis(buf, r)

        await buf.add(_actions("s1"))
        await buf.add(_actions("s2"))
        assert len(dropped) == 2


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_contains_prefix_and_window(self):
        buf = RedisEventBuffer(
            "redis://localhost:6379", key_prefix="myapp", window_seconds=60
        )
        r = repr(buf)
        assert "myapp" in r
        assert "60" in r


# ---------------------------------------------------------------------------
# Metrics hooks
# ---------------------------------------------------------------------------


def _make_metrics() -> MagicMock:
    """Return a MagicMock that satisfies the SdkMetricsHook protocol."""
    m = MagicMock(spec=SdkMetricsHook)
    return m


class TestMetricsHooks:
    @pytest.mark.asyncio
    async def test_record_redis_operation_fires_on_successful_add(self):
        metrics = _make_metrics()
        pipe = _make_pipe()
        pipe.execute = AsyncMock(return_value=[1, 1, 1])
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", metrics=metrics)
        _inject_redis(buf, r)

        await buf.add(_actions("s1"))

        metrics.record_redis_operation.assert_called_once()
        call_kwargs = metrics.record_redis_operation.call_args[1]
        assert call_kwargs["operation"] == "add"
        assert call_kwargs["success"] is True
        assert isinstance(call_kwargs["elapsed_ms"], float)

    @pytest.mark.asyncio
    async def test_record_redis_operation_fires_on_failed_add(self):
        metrics = _make_metrics()
        pipe = _make_pipe()
        pipe.execute = AsyncMock(side_effect=Exception("redis down"))
        r = _make_redis(pipe)
        buf = RedisEventBuffer("redis://localhost:6379", metrics=metrics)
        _inject_redis(buf, r)

        await buf.add(_actions("s1"))

        metrics.record_redis_operation.assert_called_once()
        call_kwargs = metrics.record_redis_operation.call_args[1]
        assert call_kwargs["operation"] == "add"
        assert call_kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_record_redis_operation_fires_on_drain(self):
        metrics = _make_metrics()
        r = _make_redis()
        r.smembers = AsyncMock(return_value={"s1"})
        pipe = _make_pipe()
        pipe.execute = AsyncMock(return_value=[[], []])
        r.pipeline = MagicMock(return_value=pipe)
        buf = RedisEventBuffer("redis://localhost:6379", metrics=metrics)
        _inject_redis(buf, r)

        await buf.drain()

        metrics.record_redis_operation.assert_called_once()
        call_kwargs = metrics.record_redis_operation.call_args[1]
        assert call_kwargs["operation"] == "drain"

    @pytest.mark.asyncio
    async def test_record_semaphore_timeout_fires_on_semaphore_timeout(self):
        metrics = _make_metrics()
        buf = RedisEventBuffer(
            "redis://localhost:6379", max_concurrent=1, metrics=metrics
        )
        # Inject Redis as available but pre-exhaust the semaphore.
        r = _make_redis()
        _inject_redis(buf, r)
        # Exhaust the semaphore so the next acquire times out.
        await buf._get_semaphore().acquire()

        await buf.add(_actions("s1"))

        metrics.record_semaphore_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_event_dropped_fires_with_correct_event_type_actions(self):
        """event_type must be 'actions', not 'actionspayload'.

        Uses port 9999 so no real Redis reconnects and the unavailable path fires.
        """
        metrics = _make_metrics()
        buf = RedisEventBuffer("redis://localhost:9999", metrics=metrics)
        buf._available = False

        await buf.add(_actions("s1"))

        metrics.record_event_dropped.assert_called_once()
        call_kwargs = metrics.record_event_dropped.call_args[1]
        assert call_kwargs["event_type"] == "actions"

    @pytest.mark.asyncio
    async def test_record_event_dropped_fires_with_correct_event_type_summary(self):
        """event_type must be 'summary', not 'summarypayload'.

        Uses port 9999 so no real Redis reconnects and the unavailable path fires.
        """
        metrics = _make_metrics()
        buf = RedisEventBuffer("redis://localhost:9999", metrics=metrics)
        buf._available = False

        await buf.add(_summary("s1"))

        metrics.record_event_dropped.assert_called_once()
        call_kwargs = metrics.record_event_dropped.call_args[1]
        assert call_kwargs["event_type"] == "summary"


# ---------------------------------------------------------------------------
# SlimAction field round-trip (validates _payload_to_json completeness)
# ---------------------------------------------------------------------------


def _rich_actions(session_id: str = "s1") -> ActionsPayload:
    """Actions payload with all SlimAction fields set to non-default values."""
    action = SlimAction(
        title="Click Export",
        description="User clicked the Export CSV button",
        canonical_url="https://app.example.com/reports",
        index=3,
        type="click",
        timestamp_start=1000.5,
        timestamp_end=1001.2,
        raw_url="https://app.example.com/reports?tab=csv",
        session_id="ps_action",
        user_id="uid_rt",
        email="rt@example.com",
    )
    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id="u1",
        email="user@example.com",
        actions=[action],
        count=1,
        forwarded_at=9999.0,
    )


class TestSlimActionRoundTrip:
    """Verify that add() → drain() preserves every SlimAction field.

    Exercises the fix for the silent field-loss bug in _payload_to_json, which
    previously omitted index, type, timestamp_start, timestamp_end, raw_url,
    and per-action identity fields.
    """

    @pytest.mark.asyncio
    async def test_all_slim_action_fields_survive_redis_round_trip(self):
        import fakeredis.aioredis as fakeredis_aioredis

        r = fakeredis_aioredis.FakeRedis(decode_responses=True)
        buf = RedisEventBuffer("redis://localhost:6379", key_prefix="roundtrip")
        buf._redis = r
        buf._available = True
        buf._semaphore = asyncio.Semaphore(buf._max_concurrent)

        original = _rich_actions("rt_sess")
        await buf.add(original)

        drained = await buf.drain()
        assert len(drained) == 1
        result = drained[0]
        assert isinstance(result, ActionsPayload)
        assert len(result.actions) == 1

        a = result.actions[0]
        orig_a = original.actions[0]

        assert a.title == orig_a.title
        assert a.description == orig_a.description
        assert a.canonical_url == orig_a.canonical_url
        assert a.index == orig_a.index
        assert a.type == orig_a.type
        assert a.timestamp_start == orig_a.timestamp_start
        assert a.timestamp_end == orig_a.timestamp_end
        assert a.raw_url == orig_a.raw_url
        assert a.session_id == orig_a.session_id
        assert a.user_id == orig_a.user_id
        assert a.email == orig_a.email
