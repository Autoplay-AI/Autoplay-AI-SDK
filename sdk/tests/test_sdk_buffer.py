"""Tests for autoplay_sdk.buffer.EventBuffer — thread-safe in-memory event buffer."""

from __future__ import annotations

import threading

from autoplay_sdk.buffer import EventBuffer
from autoplay_sdk.models import ActionsPayload, SummaryPayload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actions(session_id: str = "s1") -> ActionsPayload:
    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id=None,
        email=None,
        actions=[],
        count=0,
        forwarded_at=0.0,
    )


def _summary(session_id: str = "s1") -> SummaryPayload:
    return SummaryPayload(
        product_id="p1",
        session_id=session_id,
        summary="Summary text",
        replaces=3,
        forwarded_at=0.0,
    )


# ---------------------------------------------------------------------------
# add / drain
# ---------------------------------------------------------------------------


class TestAddDrain:
    def test_drain_returns_added_event(self):
        buf = EventBuffer()
        buf.add(_actions())
        assert len(buf.drain()) == 1

    def test_drain_clears_the_buffer(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.drain()
        assert buf.drain() == []

    def test_drain_returns_events_in_insertion_order(self):
        buf = EventBuffer()
        for i in range(5):
            buf.add(_actions(session_id=f"s{i}"))
        events = buf.drain()
        assert [e.session_id for e in events] == [f"s{i}" for i in range(5)]

    def test_drain_empty_buffer_returns_empty_list(self):
        assert EventBuffer().drain() == []

    def test_add_accepts_both_payload_types(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_summary())
        assert buf.size == 2


# ---------------------------------------------------------------------------
# peek
# ---------------------------------------------------------------------------


class TestPeek:
    def test_peek_does_not_clear_the_buffer(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.peek()
        assert buf.size == 1

    def test_peek_none_returns_all_events(self):
        buf = EventBuffer()
        buf.add(_actions("a"))
        buf.add(_summary("b"))
        assert len(buf.peek()) == 2

    def test_peek_n_returns_last_n_events(self):
        buf = EventBuffer()
        for i in range(5):
            buf.add(_actions(session_id=f"s{i}"))
        last2 = buf.peek(n=2)
        assert len(last2) == 2
        assert last2[0].session_id == "s3"
        assert last2[1].session_id == "s4"

    def test_peek_n_larger_than_buffer_returns_all(self):
        buf = EventBuffer()
        buf.add(_actions())
        assert len(buf.peek(n=100)) == 1

    def test_peek_empty_buffer_returns_empty(self):
        assert EventBuffer().peek() == []
        assert EventBuffer().peek(n=5) == []


# ---------------------------------------------------------------------------
# drain_by_type
# ---------------------------------------------------------------------------


class TestDrainByType:
    def test_drain_actions_only_leaves_summaries(self):
        buf = EventBuffer()
        buf.add(_actions("a"))
        buf.add(_summary("b"))
        result = buf.drain_by_type(actions=True, summaries=False)
        assert len(result) == 1
        assert isinstance(result[0], ActionsPayload)
        assert buf.size == 1

    def test_drain_summaries_only_leaves_actions(self):
        buf = EventBuffer()
        buf.add(_actions("a"))
        buf.add(_summary("b"))
        result = buf.drain_by_type(actions=False, summaries=True)
        assert len(result) == 1
        assert isinstance(result[0], SummaryPayload)
        assert buf.size == 1

    def test_drain_both_types_empties_buffer(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_summary())
        result = buf.drain_by_type(actions=True, summaries=True)
        assert len(result) == 2
        assert buf.size == 0

    def test_drain_neither_type_leaves_everything(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_summary())
        result = buf.drain_by_type(actions=False, summaries=False)
        assert result == []
        assert buf.size == 2

    def test_remaining_events_preserve_order(self):
        buf = EventBuffer()
        buf.add(_actions("first"))
        buf.add(_summary("keep"))
        buf.add(_actions("second"))
        buf.drain_by_type(actions=True, summaries=False)
        remaining = buf.drain()
        assert len(remaining) == 1
        assert remaining[0].session_id == "keep"


# ---------------------------------------------------------------------------
# max_size / capacity
# ---------------------------------------------------------------------------


class TestMaxSize:
    def test_oldest_event_dropped_when_buffer_is_full(self):
        buf = EventBuffer(max_size=2)
        buf.add(_actions("first"))
        buf.add(_actions("second"))
        buf.add(_actions("third"))
        events = buf.drain()
        session_ids = [e.session_id for e in events]
        assert "first" not in session_ids
        assert "second" in session_ids
        assert "third" in session_ids

    def test_max_size_zero_means_unlimited(self):
        buf = EventBuffer(max_size=0)
        for i in range(200):
            buf.add(_actions(f"s{i}"))
        assert buf.size == 200

    def test_max_size_property_reflects_constructor_arg(self):
        assert EventBuffer(max_size=42).max_size == 42
        assert EventBuffer(max_size=0).max_size == 0


# ---------------------------------------------------------------------------
# Observability: size, is_empty, __len__, __repr__, clear
# ---------------------------------------------------------------------------


class TestObservability:
    def test_size_zero_when_empty(self):
        assert EventBuffer().size == 0

    def test_size_reflects_number_of_events(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_summary())
        assert buf.size == 2

    def test_is_empty_true_when_empty(self):
        assert EventBuffer().is_empty is True

    def test_is_empty_false_after_add(self):
        buf = EventBuffer()
        buf.add(_actions())
        assert buf.is_empty is False

    def test_len_matches_size(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_actions())
        assert len(buf) == buf.size == 2

    def test_repr_contains_size_and_max_size(self):
        buf = EventBuffer(max_size=50)
        buf.add(_actions())
        r = repr(buf)
        assert "1" in r
        assert "50" in r

    def test_clear_empties_buffer_without_returning_events(self):
        buf = EventBuffer()
        buf.add(_actions())
        buf.add(_summary())
        buf.clear()
        assert buf.size == 0
        assert buf.drain() == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_adds_do_not_corrupt_buffer(self):
        buf = EventBuffer(max_size=10_000)
        errors: list[Exception] = []

        def add_many(prefix: str) -> None:
            try:
                for i in range(50):
                    buf.add(_actions(f"{prefix}_{i}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=add_many, args=(f"t{j}",)) for j in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert buf.size == 200  # 4 threads × 50 events

    def test_drain_concurrent_with_add_is_safe(self):
        buf = EventBuffer(max_size=10_000)
        drained: list = []
        errors: list[Exception] = []

        def add_loop() -> None:
            try:
                for i in range(100):
                    buf.add(_actions(f"s{i}"))
            except Exception as exc:
                errors.append(exc)

        def drain_loop() -> None:
            try:
                for _ in range(20):
                    drained.extend(buf.drain())
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=add_loop)
        t2 = threading.Thread(target=drain_loop)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        drained.extend(buf.drain())  # grab anything remaining
        assert not errors
        assert len(drained) == 100
