"""Tests for autoplay_sdk.agent_context — AsyncAgentContextWriter."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoplay_sdk.agent_context import AsyncAgentContextWriter
from autoplay_sdk.models import ActionsPayload, SlimAction
from autoplay_sdk.summarizer import AsyncSessionSummarizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(session_id: str = "sess1", n_actions: int = 1) -> ActionsPayload:
    actions = [
        SlimAction(
            title=f"A{i}",
            description=f"Did thing {i}",
            canonical_url=f"/page/{i}",
        )
        for i in range(n_actions)
    ]
    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id=None,
        email=None,
        actions=actions,
        count=n_actions,
        forwarded_at=0.0,
    )


def _make_summarizer(threshold: int = 100) -> AsyncSessionSummarizer:
    """Return a summarizer that never actually fires (threshold never reached)."""
    return AsyncSessionSummarizer(
        llm=AsyncMock(return_value="summary"),
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Construction: on_summary wiring
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_sets_summarizer_on_summary_to_internal_callback(self):
        summarizer = _make_summarizer()
        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
        )
        # Bound-method identity check: same underlying function bound to same instance.
        assert summarizer.on_summary.__func__ is AsyncAgentContextWriter._on_summary
        assert summarizer.on_summary.__self__ is writer

    def test_warns_when_existing_on_summary_is_replaced(self, caplog):
        summarizer = _make_summarizer()
        existing_cb = AsyncMock()
        summarizer.on_summary = existing_cb

        with caplog.at_level(logging.WARNING):
            AsyncAgentContextWriter(
                summarizer=summarizer,
                overwrite_with_summary=AsyncMock(),
            )

        assert "overwriting" in caplog.text.lower() or "on_summary" in caplog.text


# ---------------------------------------------------------------------------
# add(): write_actions + summarizer
# ---------------------------------------------------------------------------


class TestAdd:
    @pytest.mark.asyncio
    async def test_add_calls_write_actions_with_formatted_text(self):
        write_actions = AsyncMock()
        summarizer = _make_summarizer()
        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
        )
        payload = _payload("s1", n_actions=2)
        await writer.add(payload)
        await summarizer.flush()

        write_actions.assert_awaited_once()
        call_args = write_actions.call_args
        assert call_args[0][0] == "s1"
        assert "s1" in call_args[0][1]  # text contains session id

    @pytest.mark.asyncio
    async def test_add_feeds_payload_to_summarizer(self):
        summarizer = MagicMock(spec=AsyncSessionSummarizer)
        summarizer.on_summary = None
        summarizer.add = AsyncMock()

        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
        )
        payload = _payload("s1")
        await writer.add(payload)
        summarizer.add.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_add_still_calls_summarizer_when_write_actions_raises(self):
        """write_actions failure must not prevent the summarizer from receiving the payload."""
        summarizer = MagicMock(spec=AsyncSessionSummarizer)
        summarizer.on_summary = None
        summarizer.add = AsyncMock()

        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
            write_actions=AsyncMock(side_effect=RuntimeError("write failed")),
        )
        payload = _payload("s1")
        await writer.add(payload)  # must not raise
        summarizer.add.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_add_logs_write_actions_error(self, caplog):
        summarizer = MagicMock(spec=AsyncSessionSummarizer)
        summarizer.on_summary = None
        summarizer.add = AsyncMock()

        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
            write_actions=AsyncMock(side_effect=RuntimeError("write failed")),
        )
        with caplog.at_level(logging.ERROR):
            await writer.add(_payload("s1"))

        assert "write_actions" in caplog.text

    @pytest.mark.asyncio
    async def test_add_works_without_write_actions(self):
        """write_actions is optional; omitting it must not raise."""
        summarizer = MagicMock(spec=AsyncSessionSummarizer)
        summarizer.on_summary = None
        summarizer.add = AsyncMock()

        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
        )
        await writer.add(_payload("s1"))  # must not raise
        summarizer.add.assert_awaited_once()


# ---------------------------------------------------------------------------
# overwrite_with_summary: threshold reached
# ---------------------------------------------------------------------------


class TestOverwriteWithSummary:
    @pytest.mark.asyncio
    async def test_overwrite_is_called_when_threshold_reached(self):
        overwrite = AsyncMock()
        summarizer = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="LLM summary"),
            threshold=1,
        )
        AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=overwrite,
        )
        await summarizer.add(_payload("s1", n_actions=1))
        await summarizer.flush()

        overwrite.assert_awaited_once()
        call_args = overwrite.call_args[0]
        assert call_args[0] == "s1"
        assert "LLM summary" in call_args[1]

    @pytest.mark.asyncio
    async def test_overwrite_error_is_logged_and_does_not_raise(self, caplog):
        summarizer = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="summary"),
            threshold=1,
        )
        AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(
                side_effect=RuntimeError("overwrite boom")
            ),
        )
        with caplog.at_level(logging.ERROR):
            await summarizer.add(_payload("s1", n_actions=1))
            await summarizer.flush()

        assert "overwrite_with_summary" in caplog.text


# ---------------------------------------------------------------------------
# debounce_ms — batching write_actions calls within a time window
# ---------------------------------------------------------------------------


def _mock_summarizer() -> MagicMock:
    """Return a fully mocked summarizer with no background tasks.

    Used in debounce tests that don't care about LLM behaviour — avoids
    real AsyncSessionSummarizer worker tasks that would stall event-loop teardown.
    """
    s = MagicMock(spec=AsyncSessionSummarizer)
    s.on_summary = None
    s.add = AsyncMock()
    return s


class TestDebounce:
    """Tests for AsyncAgentContextWriter(debounce_ms=N).

    Uses debounce_ms=1 so tests complete in milliseconds; a short
    asyncio.sleep() is sufficient to let the timer fire.
    """

    @pytest.mark.asyncio
    async def test_two_payloads_same_session_produce_one_write_actions_call(self):
        """Two add() calls within the window → single write_actions with merged text."""
        write_actions = AsyncMock()
        writer = AsyncAgentContextWriter(
            summarizer=_mock_summarizer(),
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
            debounce_ms=1,
        )
        await writer.add(_payload("s1", n_actions=2))
        await writer.add(_payload("s1", n_actions=3))
        await asyncio.sleep(0.05)  # let the 1ms timer fire

        write_actions.assert_awaited_once()
        session_arg, text_arg = write_actions.call_args[0]
        assert session_arg == "s1"
        assert "5 actions" in text_arg

    @pytest.mark.asyncio
    async def test_different_sessions_produce_independent_flushes(self):
        """Payloads for different sessions flush independently."""
        write_actions = AsyncMock()
        writer = AsyncAgentContextWriter(
            summarizer=_mock_summarizer(),
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
            debounce_ms=1,
        )
        await writer.add(_payload("sessA", n_actions=1))
        await writer.add(_payload("sessB", n_actions=1))
        await asyncio.sleep(0.05)

        assert write_actions.await_count == 2
        called_sessions = {call[0][0] for call in write_actions.call_args_list}
        assert called_sessions == {"sessA", "sessB"}

    @pytest.mark.asyncio
    async def test_timer_resets_on_new_arrival(self):
        """A second add() before window expires reschedules the timer (trailing edge)."""
        write_actions = AsyncMock()
        writer = AsyncAgentContextWriter(
            summarizer=_mock_summarizer(),
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
            debounce_ms=1,
        )
        await writer.add(_payload("s1", n_actions=1))
        # Immediately add another — timer is cancelled and rescheduled.
        await writer.add(_payload("s1", n_actions=2))
        await asyncio.sleep(0.05)

        # Only one flush should have occurred (trailing edge, not leading).
        write_actions.assert_awaited_once()
        _, text_arg = write_actions.call_args[0]
        assert "3 actions" in text_arg

    @pytest.mark.asyncio
    async def test_debounce_disabled_dispatches_immediately(self):
        """debounce_ms=0 (default) must dispatch on every add() — no batching."""
        write_actions = AsyncMock()
        writer = AsyncAgentContextWriter(
            summarizer=_mock_summarizer(),
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
            # debounce_ms not set — defaults to 0
        )
        await writer.add(_payload("s1", n_actions=1))
        await writer.add(_payload("s1", n_actions=1))

        assert write_actions.await_count == 2

    @pytest.mark.asyncio
    async def test_summarizer_receives_merged_payload_with_correct_action_count(self):
        """The summarizer gets the merged payload so threshold counts total actions."""
        summarizer = _mock_summarizer()
        writer = AsyncAgentContextWriter(
            summarizer=summarizer,
            overwrite_with_summary=AsyncMock(),
            debounce_ms=1,
        )
        await writer.add(_payload("s1", n_actions=3))
        await writer.add(_payload("s1", n_actions=4))
        await asyncio.sleep(0.05)

        summarizer.add.assert_awaited_once()
        merged_payload = summarizer.add.call_args[0][0]
        assert len(merged_payload.actions) == 7
        assert merged_payload.count == 7

    @pytest.mark.asyncio
    async def test_write_actions_failure_during_flush_does_not_raise(self):
        """A write_actions error during a debounced flush must be logged, not raised."""
        write_actions = AsyncMock(side_effect=RuntimeError("dest error"))
        writer = AsyncAgentContextWriter(
            summarizer=_mock_summarizer(),
            overwrite_with_summary=AsyncMock(),
            write_actions=write_actions,
            debounce_ms=1,
        )
        await writer.add(_payload("s1"))
        await asyncio.sleep(
            0.05
        )  # flush fires; write_actions raises; task must not propagate
        # No assertion needed — test passes if no exception propagated to the test frame.
