"""Tests for autoplay_sdk.async_client — AsyncConnectorClient."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.async_client import AsyncConnectorClient  # noqa: E402
from autoplay_sdk.models import ActionsPayload, SummaryPayload  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(event: str = "message", data: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(event=event, data=data)


def _actions_data(session_id: str = "sess1") -> str:
    return json.dumps(
        {
            "type": "actions",
            "product_id": "p1",
            "session_id": session_id,
            "user_id": "u1",
            "actions": [
                {
                    "title": "Click",
                    "description": "Did something",
                    "canonical_url": "/x",
                }
            ],
            "count": 1,
            "forwarded_at": 0.0,
        }
    )


def _summary_data(session_id: str = "sess1") -> str:
    return json.dumps(
        {
            "type": "summary",
            "product_id": "p1",
            "session_id": session_id,
            "summary": "User browsed the dashboard.",
            "replaces": 5,
            "forwarded_at": 0.0,
        }
    )


# ---------------------------------------------------------------------------
# _handle: parsing and dispatch
# ---------------------------------------------------------------------------


class TestHandle:
    @pytest.mark.asyncio
    async def test_heartbeat_is_ignored(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        cb = AsyncMock()
        client.on_actions(cb)
        await client._handle(_sse(event="heartbeat", data="{}"))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_raise(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        await client._handle(_sse(data="not json"))  # must not raise

    @pytest.mark.asyncio
    async def test_unknown_event_type_is_ignored(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        cb = AsyncMock()
        client.on_actions(cb)
        await client._handle(_sse(data='{"type": "unknown_type"}'))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_actions_event_dispatches_actions_payload(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        received: list[ActionsPayload] = []
        client.on_actions(lambda p: received.append(p))
        await client._handle(_sse(data=_actions_data()))
        assert len(received) == 1
        assert isinstance(received[0], ActionsPayload)

    @pytest.mark.asyncio
    async def test_summary_event_dispatches_summary_payload(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        received: list[SummaryPayload] = []
        client.on_summary(lambda p: received.append(p))
        await client._handle(_sse(data=_summary_data()))
        assert len(received) == 1
        assert isinstance(received[0], SummaryPayload)

    @pytest.mark.asyncio
    async def test_async_callback_is_awaited(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        cb = AsyncMock()
        client.on_actions(cb)
        await client._handle(_sse(data=_actions_data()))
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_callback_is_also_supported(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        results: list[str] = []
        client.on_actions(lambda p: results.append(p.session_id))
        await client._handle(_sse(data=_actions_data("sync_sess")))
        assert results == ["sync_sess"]

    @pytest.mark.asyncio
    async def test_no_callback_registered_does_not_raise(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        await client._handle(_sse(data=_actions_data()))  # no on_actions registered

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught_and_does_not_raise(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        client.on_actions(AsyncMock(side_effect=RuntimeError("callback boom")))
        await client._handle(_sse(data=_actions_data()))  # must not raise

    @pytest.mark.asyncio
    async def test_actions_payload_has_correct_session_id(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        received: list[str] = []
        client.on_actions(lambda p: received.append(p.session_id))
        await client._handle(_sse(data=_actions_data("target_sess")))
        assert received == ["target_sess"]

    @pytest.mark.asyncio
    async def test_summary_payload_has_correct_session_id(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        received: list[str] = []
        client.on_summary(lambda p: received.append(p.session_id))
        await client._handle(_sse(data=_summary_data("sum_sess")))
        assert received == ["sum_sess"]


# ---------------------------------------------------------------------------
# Builder / method chaining
# ---------------------------------------------------------------------------


class TestBuilder:
    def test_on_actions_returns_self_for_chaining(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        assert client.on_actions(AsyncMock()) is client

    def test_on_summary_returns_self_for_chaining(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        assert client.on_summary(AsyncMock()) is client


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_running_false(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        client._running = True
        client.stop()
        assert client._running is False


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_aenter_returns_client(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        assert await client.__aenter__() is client

    @pytest.mark.asyncio
    async def test_aexit_calls_stop(self):
        client = AsyncConnectorClient(url="http://x", token="t")
        client._running = True
        await client.__aexit__(None, None, None)
        assert client._running is False

    @pytest.mark.asyncio
    async def test_async_with_block_stops_on_normal_exit(self):
        async with AsyncConnectorClient(url="http://x", token="t") as client:
            client._running = True
        assert client._running is False

    @pytest.mark.asyncio
    async def test_async_with_block_stops_on_exception(self):
        client_ref: list[AsyncConnectorClient] = []
        try:
            async with AsyncConnectorClient(url="http://x", token="t") as client:
                client._running = True
                client_ref.append(client)
                raise ValueError("something went wrong")
        except ValueError:
            pass
        assert client_ref[0]._running is False


# ---------------------------------------------------------------------------
# run_in_background()
# ---------------------------------------------------------------------------


class TestRunInBackground:
    @pytest.mark.asyncio
    async def test_returns_asyncio_task(self):
        client = AsyncConnectorClient(url="http://x", token="t")

        async def fake_run() -> None:
            client.stop()

        with patch.object(client, "run", side_effect=fake_run):
            task = client.run_in_background()

        assert isinstance(task, asyncio.Task)
        await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_run_in_background_returns_without_blocking(self):
        """run_in_background() returns immediately without waiting for the SSE loop."""
        import time

        client = AsyncConnectorClient(url="http://x", token="t")
        connected = asyncio.Event()

        async def slow_run() -> None:
            connected.set()
            await asyncio.sleep(10)  # would block if awaited

        with patch.object(client, "run", side_effect=slow_run):
            start = time.monotonic()
            task = client.run_in_background()
            elapsed = time.monotonic() - start

        # Returns immediately — did not await the task
        assert elapsed < 0.5
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Per-session semaphore isolation
# ---------------------------------------------------------------------------


class TestSessionSemaphore:
    @pytest.mark.asyncio
    async def test_same_session_second_dispatch_dropped_when_concurrency_one_busy(self):
        """With session_concurrency=1, a second dispatch for a busy session is dropped."""
        client = AsyncConnectorClient(url="http://x", token="t", session_concurrency=1)
        order: list[str] = []
        entered = asyncio.Event()

        async def slow_cb(payload: object) -> None:
            order.append("start")
            entered.set()
            await asyncio.sleep(0.05)
            order.append("end")

        client.on_actions(slow_cb)

        # Dispatch first event and wait until callback has entered the semaphore.
        t1 = asyncio.create_task(client._dispatch("sess", _actions_data_payload()))
        await entered.wait()

        # Second dispatch for the same session is dropped (semaphore is busy).
        await client._dispatch("sess", _actions_data_payload())
        await t1

        # Only one invocation ran: start → end (second was dropped)
        assert order == ["start", "end"]

    @pytest.mark.asyncio
    async def test_different_sessions_are_not_blocked_by_each_other(self):
        """Concurrent dispatches for different sessions must run concurrently."""
        client = AsyncConnectorClient(url="http://x", token="t", session_concurrency=1)
        started: list[str] = []
        barrier = asyncio.Event()

        async def barrier_cb(payload: object) -> None:
            started.append(getattr(payload, "session_id", "?"))
            # Wait for both sessions to have started before allowing either to finish.
            if len(started) == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), timeout=1.0)

        client.on_actions(barrier_cb)

        p_a = _actions_data_payload("sessA")
        p_b = _actions_data_payload("sessB")

        await asyncio.gather(
            client._dispatch("sessA", p_a),
            client._dispatch("sessB", p_b),
        )

        # Both sessions should have started — confirming they ran concurrently.
        assert set(started) == {"sessA", "sessB"}


# ---------------------------------------------------------------------------
# Reconnect / max_retries
# ---------------------------------------------------------------------------


class TestReconnect:
    @pytest.mark.asyncio
    async def test_max_retries_exhaustion_raises_sdk_upstream_error(self):
        """After max_retries failures run() raises SdkUpstreamError instead of looping."""
        from autoplay_sdk.exceptions import SdkUpstreamError

        client = AsyncConnectorClient(
            url="http://x",
            token="t",
            max_retries=0,
            initial_backoff_s=0.001,
        )

        with patch(
            "autoplay_sdk.async_client.httpx.AsyncClient",
            side_effect=ConnectionError("down"),
        ):
            with pytest.raises(SdkUpstreamError, match="max_retries"):
                await client.run()

    @pytest.mark.asyncio
    async def test_fatal_401_raises_immediately_without_retry(self):
        """HTTP 401 must be re-raised immediately without any retry loop."""
        client = AsyncConnectorClient(url="http://x", token="t", max_retries=10)

        response = MagicMock(status_code=401)
        error = httpx.HTTPStatusError("401", request=MagicMock(), response=response)

        with patch(
            "autoplay_sdk.async_client.httpx.AsyncClient",
            side_effect=error,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.run()

    @pytest.mark.asyncio
    async def test_fatal_403_raises_immediately_without_retry(self):
        client = AsyncConnectorClient(url="http://x", token="t", max_retries=10)

        response = MagicMock(status_code=403)
        error = httpx.HTTPStatusError("403", request=MagicMock(), response=response)

        with patch(
            "autoplay_sdk.async_client.httpx.AsyncClient",
            side_effect=error,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.run()

    @pytest.mark.asyncio
    async def test_on_connect_callback_is_invoked(self):
        """on_connect is called by _fire_on_connect, which run() calls after connecting."""
        on_connect = AsyncMock()
        client = AsyncConnectorClient(url="http://x", token="t", on_connect=on_connect)
        await client._fire_on_connect()
        on_connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_connect_sync_callback_is_supported(self):
        called: list[int] = []
        client = AsyncConnectorClient(
            url="http://x", token="t", on_connect=lambda: called.append(1)
        )
        await client._fire_on_connect()
        assert called == [1]

    @pytest.mark.asyncio
    async def test_on_disconnect_callback_is_invoked(self):
        """on_disconnect is called by _fire_on_disconnect, which run() calls on failure."""
        on_disconnect = AsyncMock()
        client = AsyncConnectorClient(
            url="http://x", token="t", on_disconnect=on_disconnect
        )
        await client._fire_on_disconnect()
        on_disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_disconnect_called_during_run_on_connection_error(self):
        """on_disconnect is fired when a transient error causes a reconnect."""
        on_disconnect = AsyncMock()
        client = AsyncConnectorClient(
            url="http://x",
            token="t",
            max_retries=0,
            initial_backoff_s=0.001,
            on_disconnect=on_disconnect,
        )
        from autoplay_sdk.exceptions import SdkUpstreamError

        with patch(
            "autoplay_sdk.async_client.httpx.AsyncClient",
            side_effect=ConnectionError("dropped"),
        ):
            with pytest.raises(SdkUpstreamError, match="max_retries"):
                await client.run()

        on_disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# Helpers shared by new test classes
# ---------------------------------------------------------------------------


def _actions_data_payload(session_id: str = "sess1") -> "ActionsPayload":
    """Return a minimal ActionsPayload (parsed, not raw SSE)."""
    from autoplay_sdk.models import ActionsPayload

    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id=None,
        email=None,
        actions=[],
        count=0,
        forwarded_at=0.0,
    )


# ---------------------------------------------------------------------------
# Item 6 — AsyncConnectorClient: wired metrics hooks
# ---------------------------------------------------------------------------


class TestAsyncConnectorClientMetrics:
    @pytest.mark.asyncio
    async def test_record_event_dropped_fires_when_semaphore_full(self):
        """record_event_dropped is called when the session semaphore is saturated."""
        dropped_calls: list[dict] = []

        class MyMetrics:
            def record_event_dropped(
                self, *, reason, event_type, session_id, product_id
            ):
                dropped_calls.append(
                    {
                        "reason": reason,
                        "event_type": event_type,
                        "session_id": session_id,
                    }
                )

        gate = asyncio.Event()

        async def slow_callback(payload):
            await gate.wait()

        client = AsyncConnectorClient(
            url="http://x",
            session_concurrency=1,  # only 1 slot per session
            metrics=MyMetrics(),
        )
        client.on_actions(slow_callback)

        payload = _actions_data_payload("s1")

        # First dispatch acquires the sole semaphore slot and blocks on the gate.
        first = asyncio.create_task(client._dispatch("s1", payload))
        await asyncio.sleep(0.02)  # let first task acquire the slot

        # Second dispatch should find the slot busy and drop.
        await client._dispatch("s1", payload)

        gate.set()
        await first

        assert len(dropped_calls) == 1
        assert dropped_calls[0]["reason"] == "queue_full"
        assert dropped_calls[0]["event_type"] == "actions"
        assert dropped_calls[0]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_record_queue_depth_fires_on_successful_dispatch(self):
        """record_queue_depth is called after acquiring a session semaphore slot."""
        depth_calls: list[int] = []

        class MyMetrics:
            def record_queue_depth(self, *, depth):
                depth_calls.append(depth)

        async def noop(payload):
            pass

        client = AsyncConnectorClient(url="http://x", metrics=MyMetrics())
        client.on_actions(noop)

        payload = _actions_data_payload("s1")
        await client._dispatch("s1", payload)

        assert len(depth_calls) == 1
        assert depth_calls[0] >= 1

    @pytest.mark.asyncio
    async def test_no_metrics_does_not_raise(self):
        """AsyncConnectorClient without metrics=... dispatches without error."""

        async def noop(payload):
            pass

        client = AsyncConnectorClient(url="http://x")
        client.on_actions(noop)
        payload = _actions_data_payload("s2")
        await client._dispatch("s2", payload)  # must not raise


# ---------------------------------------------------------------------------
# Item 4 — SdkUpstreamError raised by AsyncConnectorClient
# ---------------------------------------------------------------------------


class TestAsyncConnectorClientExceptions:
    @pytest.mark.asyncio
    async def test_max_retries_exhausted_raises_sdk_upstream_error(self):
        """When max_retries is exhausted, SdkUpstreamError is raised."""
        from autoplay_sdk.exceptions import SdkUpstreamError

        client = AsyncConnectorClient(
            url="http://x",
            max_retries=0,
            initial_backoff_s=0.001,
            max_backoff_s=0.001,
        )
        with patch(
            "autoplay_sdk.async_client.httpx.AsyncClient",
            side_effect=ConnectionError("down"),
        ):
            with pytest.raises(SdkUpstreamError):
                await client.run()

    def test_sdk_upstream_error_is_sdk_error_subclass(self):
        """SdkUpstreamError must be a subclass of SdkError."""
        from autoplay_sdk.exceptions import SdkError, SdkUpstreamError

        assert issubclass(SdkUpstreamError, SdkError)
