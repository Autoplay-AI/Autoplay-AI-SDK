"""Unit tests for the customer SDK ConnectorClient.

Tests cover:
- Callback invocation for actions and summary events
- Worker thread decoupling (callback runs off the receive thread)
- Queue-full drop counting and logging
- dropped_count property
- Heartbeat and unknown event types are silently ignored
- Malformed JSON is logged and skipped
- stop() signals clean shutdown
- _WORKER_STOP sentinel drains the queue cleanly
- on_drop callback invoked with payload and total count
- queue_size property reflects current queue depth
- run_in_background() starts run() on a daemon thread
- Context manager calls stop() on __exit__
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from autoplay_sdk.client import _WORKER_STOP, ConnectorClient
from autoplay_sdk.models import ActionsPayload, SummaryPayload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(event: str = "message", data: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(event=event, data=data)


def _actions_payload(session_id: str = "sess1") -> dict:
    return {
        "type": "actions",
        "product_id": "prod1",
        "session_id": session_id,
        "user_id": "u1",
        "actions": [
            {"title": "CLICK btn", "description": "desc", "canonical_url": "/page"}
        ],
        "count": 1,
        "forwarded_at": 1234567890.0,
    }


def _summary_payload() -> dict:
    return {
        "type": "summary",
        "product_id": "prod1",
        "session_id": "sess1",
        "summary": "User browsed and checked out.",
        "replaces": 5,
        "forwarded_at": 1234567890.0,
    }


# ---------------------------------------------------------------------------
# _enqueue: routing and filtering
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_heartbeat_is_ignored(self):
        client = ConnectorClient(url="http://x", token="t")
        client._enqueue(_sse(event="heartbeat", data="{}"))
        assert client._queue.empty()

    def test_unknown_event_type_is_ignored(self):
        client = ConnectorClient(url="http://x", token="t")
        client._enqueue(_sse(data='{"type": "unknown_thing"}'))
        assert client._queue.empty()

    def test_malformed_json_is_skipped(self):
        client = ConnectorClient(url="http://x", token="t")
        client._enqueue(_sse(data="not json"))
        assert client._queue.empty()
        assert client._dropped == 0  # not a drop — just a parse error

    def test_actions_event_placed_on_queue(self):
        client = ConnectorClient(url="http://x", token="t")
        import json

        client._enqueue(_sse(data=json.dumps(_actions_payload())))
        assert client._queue.qsize() == 1

    def test_summary_event_placed_on_queue(self):
        client = ConnectorClient(url="http://x", token="t")
        import json

        client._enqueue(_sse(data=json.dumps(_summary_payload())))
        assert client._queue.qsize() == 1

    def test_full_queue_increments_dropped_count(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=1)
        import json

        payload_json = json.dumps(_actions_payload())
        client._enqueue(_sse(data=payload_json))  # fills queue
        client._enqueue(_sse(data=payload_json))  # dropped
        assert client._dropped == 1

    def test_dropped_count_property_reflects_drops(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=1)
        import json

        payload_json = json.dumps(_actions_payload())
        client._enqueue(_sse(data=payload_json))
        client._enqueue(_sse(data=payload_json))
        client._enqueue(_sse(data=payload_json))
        assert client.dropped_count == 2


# ---------------------------------------------------------------------------
# _dispatch: callback routing
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_actions_callback_called_with_payload(self):
        client = ConnectorClient(url="http://x", token="t")
        cb = MagicMock()
        client.on_actions(cb)
        client._dispatch(_actions_payload())
        cb.assert_called_once()
        assert isinstance(cb.call_args[0][0], ActionsPayload)

    def test_summary_callback_called_with_payload(self):
        client = ConnectorClient(url="http://x", token="t")
        cb = MagicMock()
        client.on_summary(cb)
        client._dispatch(_summary_payload())
        cb.assert_called_once()
        assert isinstance(cb.call_args[0][0], SummaryPayload)

    def test_no_callback_registered_does_not_raise(self):
        client = ConnectorClient(url="http://x", token="t")
        client._dispatch(_actions_payload())  # no on_actions registered

    def test_callback_exception_is_caught_and_logged(self):
        client = ConnectorClient(url="http://x", token="t")
        client.on_actions(MagicMock(side_effect=RuntimeError("boom")))
        client._dispatch(_actions_payload())  # must not raise


# ---------------------------------------------------------------------------
# Worker thread: decoupling
# ---------------------------------------------------------------------------


class TestWorkerThread:
    def test_worker_processes_queued_payload(self):
        """Payload put directly on the queue is picked up and dispatched."""
        client = ConnectorClient(url="http://x", token="t")
        received: list[dict] = []
        client.on_actions(received.append)

        worker = threading.Thread(target=client._worker_loop, daemon=True)
        worker.start()

        client._queue.put(_actions_payload())
        client._queue.put(_WORKER_STOP)
        worker.join(timeout=2)

        assert len(received) == 1
        assert isinstance(received[0], ActionsPayload)

    def test_worker_processes_multiple_payloads_in_order(self):
        client = ConnectorClient(url="http://x", token="t")
        received: list[str] = []
        client.on_actions(lambda p: received.append(p.session_id))

        worker = threading.Thread(target=client._worker_loop, daemon=True)
        worker.start()

        for i in range(5):
            client._queue.put(_actions_payload(session_id=f"sess{i}"))
        client._queue.put(_WORKER_STOP)
        worker.join(timeout=2)

        assert received == [f"sess{i}" for i in range(5)]

    def test_callback_runs_on_worker_thread_not_caller_thread(self):
        """The callback must not execute on the thread that called _enqueue."""
        client = ConnectorClient(url="http://x", token="t")
        import json

        callback_thread_ids: list[int] = []
        client.on_actions(lambda _: callback_thread_ids.append(threading.get_ident()))

        worker = threading.Thread(target=client._worker_loop, daemon=True)
        worker.start()

        client._enqueue(_sse(data=json.dumps(_actions_payload())))
        client._queue.put(_WORKER_STOP)
        worker.join(timeout=2)

        assert len(callback_thread_ids) == 1
        assert callback_thread_ids[0] != threading.get_ident()

    def test_slow_callback_does_not_block_enqueue(self):
        """Even if the callback is slow, _enqueue returns immediately."""
        client = ConnectorClient(url="http://x", token="t", max_queue_size=10)
        import json

        barrier = threading.Event()

        def slow_cb(_):
            barrier.wait(timeout=5)

        client.on_actions(slow_cb)

        worker = threading.Thread(target=client._worker_loop, daemon=True)
        worker.start()

        payload_json = json.dumps(_actions_payload())
        start = time.monotonic()
        # Enqueue multiple events while the worker is blocked
        for _ in range(3):
            client._enqueue(_sse(data=payload_json))
        elapsed = time.monotonic() - start

        barrier.set()
        client._queue.put(_WORKER_STOP)
        worker.join(timeout=5)

        # All three enqueues returned in well under 1s despite slow callback
        assert elapsed < 0.5


# ---------------------------------------------------------------------------
# stop() and clean shutdown
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_running_false(self):
        client = ConnectorClient(url="http://x", token="t")
        client._running = True
        client.stop()
        assert client._running is False

    def test_run_exits_cleanly_when_sse_raises_keyboard_interrupt(self):
        """Simulates Ctrl-C during the SSE loop — run() must return cleanly."""
        client = ConnectorClient(url="http://x", token="t")

        with (
            patch("autoplay_sdk.client.connect_sse") as mock_sse,
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(side_effect=KeyboardInterrupt)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_sse.return_value = mock_ctx

            client.run()  # must not raise

        # KeyboardInterrupt sets _running = False so repr/lifecycle observers
        # see consistent stopped state (same as calling stop() explicitly).
        assert client._running is False


# ---------------------------------------------------------------------------
# on_drop callback
# ---------------------------------------------------------------------------


class TestOnDrop:
    def test_on_drop_called_when_queue_full(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=1)
        import json

        drop_calls: list[tuple] = []
        client.on_drop(lambda p, n: drop_calls.append((p["type"], n)))

        payload_json = json.dumps(_actions_payload())
        client._enqueue(_sse(data=payload_json))  # fills queue
        client._enqueue(_sse(data=payload_json))  # triggers drop

        assert len(drop_calls) == 1
        assert drop_calls[0] == ("actions", 1)

    def test_on_drop_receives_cumulative_count(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=1)
        import json

        counts: list[int] = []
        client.on_drop(lambda p, n: counts.append(n))

        payload_json = json.dumps(_actions_payload())
        client._enqueue(_sse(data=payload_json))  # fills queue
        client._enqueue(_sse(data=payload_json))  # drop 1
        client._enqueue(_sse(data=payload_json))  # drop 2

        assert counts == [1, 2]

    def test_on_drop_not_called_when_queue_has_space(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=10)
        import json

        drop_calls: list = []
        client.on_drop(lambda p, n: drop_calls.append(n))

        client._enqueue(_sse(data=json.dumps(_actions_payload())))
        assert drop_calls == []

    def test_on_drop_exception_does_not_propagate(self):
        client = ConnectorClient(url="http://x", token="t", max_queue_size=1)
        import json

        client.on_drop(MagicMock(side_effect=RuntimeError("drop handler boom")))
        payload_json = json.dumps(_actions_payload())
        client._enqueue(_sse(data=payload_json))  # fills queue
        client._enqueue(_sse(data=payload_json))  # must not raise


# ---------------------------------------------------------------------------
# queue_size property
# ---------------------------------------------------------------------------


class TestQueueSize:
    def test_queue_size_zero_when_empty(self):
        client = ConnectorClient(url="http://x", token="t")
        assert client.queue_size == 0

    def test_queue_size_reflects_enqueued_items(self):
        import json

        client = ConnectorClient(url="http://x", token="t")
        client._enqueue(_sse(data=json.dumps(_actions_payload())))
        client._enqueue(_sse(data=json.dumps(_summary_payload())))
        assert client.queue_size == 2

    def test_queue_size_decreases_after_worker_drains(self):
        import json

        client = ConnectorClient(url="http://x", token="t")
        client.on_actions(lambda _: None)

        worker = threading.Thread(target=client._worker_loop, daemon=True)
        worker.start()

        client._enqueue(_sse(data=json.dumps(_actions_payload())))
        client._queue.put(_WORKER_STOP)
        worker.join(timeout=2)

        assert client.queue_size == 0


# ---------------------------------------------------------------------------
# run_in_background()
# ---------------------------------------------------------------------------


class TestRunInBackground:
    def test_returns_a_thread(self):
        client = ConnectorClient(url="http://x", token="t")

        with (
            patch("autoplay_sdk.client.connect_sse") as mock_sse,
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(side_effect=KeyboardInterrupt)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_sse.return_value = mock_ctx

            t = client.run_in_background()

        assert isinstance(t, threading.Thread)

    def test_returned_thread_is_daemon(self):
        client = ConnectorClient(url="http://x", token="t")

        with (
            patch("autoplay_sdk.client.connect_sse") as mock_sse,
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(side_effect=KeyboardInterrupt)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_sse.return_value = mock_ctx

            t = client.run_in_background()

        assert t.daemon is True

    def test_run_in_background_does_not_block_caller(self):
        """run_in_background() must return before the SSE loop connects."""
        client = ConnectorClient(url="http://x", token="t")
        connected = threading.Event()

        def fake_connect(*_args, **_kwargs):
            connected.set()
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(side_effect=KeyboardInterrupt)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        with (
            patch("autoplay_sdk.client.connect_sse", side_effect=fake_connect),
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            start = time.monotonic()
            client.run_in_background()
            elapsed = time.monotonic() - start

        assert elapsed < 1.0  # returned immediately, did not wait for connection


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_enter_returns_client(self):
        client = ConnectorClient(url="http://x", token="t")
        assert client.__enter__() is client

    def test_exit_calls_stop(self):
        client = ConnectorClient(url="http://x", token="t")
        client._running = True
        client.__exit__(None, None, None)
        assert client._running is False

    def test_with_block_calls_stop_on_normal_exit(self):
        with ConnectorClient(url="http://x", token="t") as client:
            client._running = True
        assert client._running is False

    def test_with_block_calls_stop_on_exception(self):
        client_ref: list[ConnectorClient] = []
        try:
            with ConnectorClient(url="http://x", token="t") as client:
                client._running = True
                client_ref.append(client)
                raise ValueError("something went wrong")
        except ValueError:
            pass
        assert client_ref[0]._running is False


# ---------------------------------------------------------------------------
# max_retries
# ---------------------------------------------------------------------------


class TestMaxRetries:
    def test_max_retries_raises_sdk_upstream_error_after_exhaustion(self):
        """run() raises SdkUpstreamError once max_retries transient failures are exceeded."""
        from autoplay_sdk.exceptions import SdkUpstreamError

        client = ConnectorClient(
            url="http://x",
            token="t",
            max_retries=2,
            initial_backoff_s=0.001,
            max_backoff_s=0.001,
        )

        attempt = 0

        def fake_connect_sse(*_a, **_kw):
            nonlocal attempt
            attempt += 1
            raise ConnectionError("network down")

        with (
            patch("autoplay_sdk.client.connect_sse", side_effect=fake_connect_sse),
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            with pytest.raises(SdkUpstreamError, match="max_retries=2"):
                client.run()

        assert attempt == 3  # initial + 2 retries

    def test_max_retries_none_does_not_limit(self):
        """max_retries=None (default) never raises RuntimeError from retry exhaustion."""
        client = ConnectorClient(
            url="http://x",
            token="t",
            max_retries=None,
            initial_backoff_s=0.001,
            max_backoff_s=0.001,
        )
        call_count = 0

        def fake_connect_sse(*_a, **_kw):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                client.stop()
                return
            raise ConnectionError("network down")

        with (
            patch("autoplay_sdk.client.connect_sse", side_effect=fake_connect_sse),
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            client.run()  # must not raise

    def test_invalid_max_retries_raises(self):
        import pytest

        with pytest.raises(ValueError, match="max_retries"):
            ConnectorClient(url="http://x", max_retries=-1)

    def test_initial_backoff_s_parameter_used(self):
        """initial_backoff_s replaces the old module-level constant."""
        client = ConnectorClient(
            url="http://x", initial_backoff_s=0.5, max_backoff_s=1.0
        )
        assert client._initial_backoff_s == 0.5
        assert client._max_backoff_s == 1.0


# ---------------------------------------------------------------------------
# Metrics hook
# ---------------------------------------------------------------------------


class TestMetricsHook:
    def test_record_event_dropped_called_on_queue_full(self):
        """SdkMetricsHook.record_event_dropped is called when the queue is full."""
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

        client = ConnectorClient(url="http://x", max_queue_size=1, metrics=MyMetrics())
        # Fill the queue with one item so the next enqueue drops.
        client._queue.put_nowait({"type": "actions", "session_id": "s1"})

        client._enqueue(
            SimpleNamespace(
                event="message", data='{"type":"actions","session_id":"drop_me"}'
            )
        )

        assert len(dropped_calls) == 1
        assert dropped_calls[0]["reason"] == "queue_full"
        assert dropped_calls[0]["event_type"] == "actions"

    def test_record_queue_depth_called_on_enqueue(self):
        """SdkMetricsHook.record_queue_depth is called after a successful enqueue."""
        depth_calls: list[int] = []

        class MyMetrics:
            def record_queue_depth(self, *, depth):
                depth_calls.append(depth)

        client = ConnectorClient(url="http://x", metrics=MyMetrics())
        client._enqueue(
            SimpleNamespace(
                event="message",
                data='{"type":"actions","session_id":"s","product_id":"p",'
                '"user_id":null,"email":null,"actions":[],"count":0,"forwarded_at":0}',
            )
        )
        assert len(depth_calls) == 1
        assert depth_calls[0] >= 1

    def test_metrics_none_does_not_raise(self):
        """Passing metrics=None (default) does not affect normal operation."""
        client = ConnectorClient(url="http://x")
        assert client._metrics is None
        # Should not raise
        client._enqueue(
            SimpleNamespace(
                event="message",
                data='{"type":"actions","session_id":"s","product_id":"p",'
                '"user_id":null,"email":null,"actions":[],"count":0,"forwarded_at":0}',
            )
        )


# ---------------------------------------------------------------------------
# Item 5 — ConnectorClient: configurable timeouts
# ---------------------------------------------------------------------------


class TestConnectorClientTimeouts:
    def test_default_timeout_has_connect_set_and_read_none(self):
        """Default constructor creates an httpx.Timeout with connect set and read=None."""
        import httpx

        client = ConnectorClient(url="http://x", connect_timeout=5.0)
        # Reconstruct what run() will build
        timeout = httpx.Timeout(
            connect=client._connect_timeout,
            read=client._read_timeout_s,
            write=None,
            pool=None,
        )
        assert timeout.connect == 5.0
        assert timeout.read is None

    def test_read_timeout_s_param_stored_on_instance(self):
        """read_timeout_s is stored and accessible on the instance."""
        client = ConnectorClient(url="http://x", read_timeout_s=30.0)
        assert client._read_timeout_s == 30.0

    def test_read_timeout_s_defaults_to_none(self):
        """read_timeout_s defaults to None (stream indefinitely)."""
        client = ConnectorClient(url="http://x")
        assert client._read_timeout_s is None

    def test_custom_timeouts_reflected_in_httpx_timeout_object(self):
        """Both connect and read timeout values are correctly reflected."""
        import httpx

        client = ConnectorClient(
            url="http://x", connect_timeout=7.5, read_timeout_s=60.0
        )
        timeout = httpx.Timeout(
            connect=client._connect_timeout,
            read=client._read_timeout_s,
            write=None,
            pool=None,
        )
        assert timeout.connect == 7.5
        assert timeout.read == 60.0


# ---------------------------------------------------------------------------
# Item 4 — Structured exceptions raised by ConnectorClient
# ---------------------------------------------------------------------------


class TestConnectorClientExceptions:
    def test_max_retries_exhausted_raises_sdk_upstream_error(self):
        """When max_retries is exhausted, SdkUpstreamError is raised (not RuntimeError)."""
        from autoplay_sdk.exceptions import SdkUpstreamError

        client = ConnectorClient(
            url="http://x",
            max_retries=0,
            initial_backoff_s=0.01,
            max_backoff_s=0.01,
        )

        with (
            patch(
                "autoplay_sdk.client.connect_sse",
                side_effect=OSError("connection refused"),
            ),
            patch("autoplay_sdk.client.httpx.Client"),
        ):
            with pytest.raises(SdkUpstreamError):
                client.run()

    def test_sdk_upstream_error_is_sdk_error_subclass(self):
        """SdkUpstreamError must be a subclass of SdkError."""
        from autoplay_sdk.exceptions import SdkError, SdkUpstreamError

        assert issubclass(SdkUpstreamError, SdkError)
