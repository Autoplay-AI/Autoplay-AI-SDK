"""Tests for autoplay_sdk.summarizer — SessionSummarizer and AsyncSessionSummarizer."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.models import ActionsPayload, SlimAction  # noqa: E402
from autoplay_sdk.summarizer import (  # noqa: E402
    DEFAULT_PROMPT,
    AsyncSessionSummarizer,
    SessionSummarizer,
    _format_actions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(session_id: str = "sess1", n_actions: int = 1) -> ActionsPayload:
    actions = [
        SlimAction(
            title=f"A{i}", description=f"Did thing {i}", canonical_url=f"/page/{i}"
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


# ---------------------------------------------------------------------------
# _format_actions helper
# ---------------------------------------------------------------------------


class TestFormatActions:
    def test_produces_numbered_list(self):
        text = _format_actions([_payload(n_actions=2)])
        lines = text.splitlines()
        assert lines[0].startswith("1.")
        assert lines[1].startswith("2.")

    def test_empty_list_returns_empty_string(self):
        assert _format_actions([]) == ""

    def test_actions_across_multiple_payloads_numbered_consecutively(self):
        text = _format_actions([_payload(n_actions=2), _payload(n_actions=2)])
        lines = text.splitlines()
        assert lines[0].startswith("1.")
        assert lines[3].startswith("4.")

    def test_each_line_contains_action_text(self):
        text = _format_actions([_payload(n_actions=1)])
        assert "Did thing 0" in text


# ---------------------------------------------------------------------------
# SessionSummarizer (sync)
# ---------------------------------------------------------------------------


class TestSessionSummarizer:
    def test_no_summary_triggered_below_threshold(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"), threshold=5, on_summary=on_summary
        )
        s.add(_payload(n_actions=4))
        on_summary.assert_not_called()

    def test_summary_triggered_exactly_at_threshold(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"), threshold=3, on_summary=on_summary
        )
        s.add(_payload(n_actions=3))
        on_summary.assert_called_once()

    def test_summary_triggered_above_threshold(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"), threshold=3, on_summary=on_summary
        )
        s.add(_payload(n_actions=5))
        on_summary.assert_called_once()

    def test_on_summary_called_with_correct_session_id_and_text(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="My summary"), threshold=1, on_summary=on_summary
        )
        s.add(_payload("sess_x", n_actions=1))
        on_summary.assert_called_once_with("sess_x", "My summary")

    def test_history_is_cleared_after_summary(self):
        s = SessionSummarizer(llm=MagicMock(return_value="S"), threshold=2)
        s.add(_payload(n_actions=2))
        assert s.get_context("sess1") == ""

    def test_action_count_resets_after_summary(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"), threshold=2, on_summary=on_summary
        )
        s.add(_payload(n_actions=2))  # first summary
        on_summary.reset_mock()
        s.add(_payload(n_actions=1))  # count is 1 now, below threshold
        on_summary.assert_not_called()

    def test_multiple_sessions_are_independent(self):
        summaries: list[str] = []
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"),
            threshold=3,
            on_summary=lambda sid, _: summaries.append(sid),
        )
        s.add(_payload("alice", n_actions=3))  # triggers
        s.add(_payload("bob", n_actions=2))  # does not trigger
        assert summaries == ["alice"]

    def test_none_session_id_uses_unknown_as_key(self):
        on_summary = MagicMock()
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"), threshold=1, on_summary=on_summary
        )
        payload = _payload(n_actions=1)
        payload.session_id = None
        s.add(payload)
        on_summary.assert_called_once_with("unknown", "S")

    def test_get_context_returns_formatted_actions_before_threshold(self):
        s = SessionSummarizer(llm=MagicMock(), threshold=10)
        s.add(_payload(n_actions=3))
        ctx = s.get_context("sess1")
        assert "1." in ctx
        assert ctx != ""

    def test_get_context_returns_empty_string_for_unknown_session(self):
        assert (
            SessionSummarizer(llm=MagicMock(), threshold=10).get_context(
                "does_not_exist"
            )
            == ""
        )

    def test_reset_clears_history_without_triggering_on_summary(self):
        on_summary = MagicMock()
        s = SessionSummarizer(llm=MagicMock(), threshold=10, on_summary=on_summary)
        s.add(_payload(n_actions=5))
        s.reset("sess1")
        on_summary.assert_not_called()
        assert s.get_context("sess1") == ""

    def test_active_sessions_includes_sessions_with_pending_actions(self):
        s = SessionSummarizer(llm=MagicMock(), threshold=10)
        s.add(_payload("alice", n_actions=1))
        s.add(_payload("bob", n_actions=2))
        assert set(s.active_sessions) == {"alice", "bob"}

    def test_active_sessions_empty_after_threshold_reached(self):
        s = SessionSummarizer(llm=MagicMock(return_value="S"), threshold=1)
        s.add(_payload("alice", n_actions=1))
        assert "alice" not in s.active_sessions

    def test_llm_exception_is_caught_and_does_not_raise(self):
        s = SessionSummarizer(
            llm=MagicMock(side_effect=RuntimeError("LLM down")), threshold=1
        )
        s.add(_payload(n_actions=1))  # must not raise

    def test_custom_prompt_template_is_used_instead_of_default(self):
        captured: list[str] = []

        def llm(prompt: str) -> str:
            captured.append(prompt)
            return "S"

        s = SessionSummarizer(llm=llm, threshold=1, prompt="Custom: {actions}")
        s.add(_payload(n_actions=1))
        assert captured[0].startswith("Custom:")

    def test_default_prompt_is_used_when_prompt_is_none(self):
        captured: list[str] = []

        def llm(prompt: str) -> str:
            captured.append(prompt)
            return "S"

        s = SessionSummarizer(llm=llm, threshold=1, prompt=None)
        s.add(_payload(n_actions=1))
        # Placeholder must have been filled — raw {actions} should not appear
        assert "{actions}" not in captured[0]
        assert len(captured[0]) > 0

    def test_on_summary_can_be_set_after_construction(self):
        on_summary = MagicMock()
        s = SessionSummarizer(llm=MagicMock(return_value="S"), threshold=1)
        s.on_summary = on_summary
        s.add(_payload(n_actions=1))
        on_summary.assert_called_once()


# ---------------------------------------------------------------------------
# AsyncSessionSummarizer
# ---------------------------------------------------------------------------


class TestAsyncSessionSummarizer:
    @pytest.mark.asyncio
    async def test_no_summary_below_threshold(self):
        on_summary = AsyncMock()
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"), threshold=5, on_summary=on_summary
        )
        await s.add(_payload(n_actions=4))
        await s.flush()
        on_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_summary_triggered_at_threshold(self):
        on_summary = AsyncMock()
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"), threshold=3, on_summary=on_summary
        )
        await s.add(_payload(n_actions=3))
        await s.flush()
        on_summary.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_summary_called_with_session_id_and_text(self):
        on_summary = AsyncMock()
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="Async summary"),
            threshold=1,
            on_summary=on_summary,
        )
        await s.add(_payload("async_sess", n_actions=1))
        await s.flush()
        on_summary.assert_awaited_once_with("async_sess", "Async summary")

    @pytest.mark.asyncio
    async def test_history_cleared_after_summary(self):
        s = AsyncSessionSummarizer(llm=AsyncMock(return_value="S"), threshold=2)
        await s.add(_payload(n_actions=2))
        await s.flush()
        assert await s.get_context("sess1") == ""

    @pytest.mark.asyncio
    async def test_multiple_sessions_are_independent(self):
        results: list[str] = []

        async def on_summary(sid: str, txt: str) -> None:
            results.append(sid)

        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"), threshold=2, on_summary=on_summary
        )
        await s.add(_payload("alice", n_actions=2))
        await s.add(_payload("bob", n_actions=1))
        await s.flush()
        assert results == ["alice"]

    @pytest.mark.asyncio
    async def test_none_session_id_uses_unknown(self):
        results: list[str] = []

        async def on_summary(sid: str, txt: str) -> None:
            results.append(sid)

        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"), threshold=1, on_summary=on_summary
        )
        payload = _payload(n_actions=1)
        payload.session_id = None
        await s.add(payload)
        await s.flush()
        assert results == ["unknown"]

    @pytest.mark.asyncio
    async def test_llm_exception_is_caught_and_does_not_raise(self):
        s = AsyncSessionSummarizer(
            llm=AsyncMock(side_effect=RuntimeError("LLM down")), threshold=1
        )
        await s.add(_payload(n_actions=1))
        await s.flush()  # must not raise

    @pytest.mark.asyncio
    async def test_sync_on_summary_callback_is_supported(self):
        """AsyncSessionSummarizer tolerates a plain sync on_summary callable."""
        results: list[str] = []
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"),
            threshold=1,
            on_summary=lambda sid, txt: results.append(sid),
        )
        await s.add(_payload("sync_sess", n_actions=1))
        await s.flush()
        assert results == ["sync_sess"]

    @pytest.mark.asyncio
    async def test_get_context_returns_formatted_actions_before_threshold(self):
        s = AsyncSessionSummarizer(llm=AsyncMock(), threshold=10)
        await s.add(_payload(n_actions=2))
        await s.flush()
        ctx = await s.get_context("sess1")
        assert "1." in ctx

    @pytest.mark.asyncio
    async def test_reset_clears_without_calling_on_summary(self):
        on_summary = AsyncMock()
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"), threshold=10, on_summary=on_summary
        )
        await s.add(_payload(n_actions=5))
        await s.reset("sess1")
        await s.flush()
        on_summary.assert_not_awaited()
        assert await s.get_context("sess1") == ""

    @pytest.mark.asyncio
    async def test_ordering_preserved_after_llm_failure(self):
        """Actions arriving during a failed LLM call must be re-queued in order.

        Timeline:
        1. 5 actions arrive → threshold hit → snapshot taken → LLM fails.
        2. 3 more actions arrive while LLM call is in progress.
        3. Failure path restores the snapshot BEFORE the new 3 actions.
        4. On the next threshold trigger the on_summary fires for the full 8.
        """
        summary_calls: list[str] = []

        async def on_summary(sid: str, text: str) -> None:
            summary_calls.append(text)

        llm_call_count = 0

        async def flaky_llm(prompt: str) -> str:
            nonlocal llm_call_count
            llm_call_count += 1
            if llm_call_count == 1:
                raise RuntimeError("transient LLM failure")
            return f"summary_{llm_call_count}"

        s = AsyncSessionSummarizer(llm=flaky_llm, threshold=5, on_summary=on_summary)
        # First batch: hits threshold, LLM fails, history restored.
        await s.add(_payload(n_actions=5))
        await s.flush()
        assert summary_calls == [], "LLM failed — no summary yet"

        # Second batch: count now 5 (restored) + 3 = 8, threshold 5 hit again.
        await s.add(_payload(n_actions=3))
        await s.flush()
        assert len(summary_calls) == 1, "Second LLM call should produce summary"
        assert summary_calls[0].startswith("summary_")

    @pytest.mark.asyncio
    async def test_metrics_hook_receives_summarizer_latency(self):
        """SdkMetricsHook.record_summarizer_latency is called after a successful LLM call."""

        latency_calls: list[dict] = []

        class MyMetrics:
            def record_summarizer_latency(
                self, *, session_id, elapsed_ms, action_count
            ):
                latency_calls.append(
                    {"session_id": session_id, "action_count": action_count}
                )

        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="S"),
            threshold=2,
            metrics=MyMetrics(),
        )
        await s.add(_payload("m1", n_actions=2))
        await s.flush()
        assert latency_calls == [{"session_id": "m1", "action_count": 2}]

    @pytest.mark.asyncio
    async def test_flush_is_idempotent_with_no_active_sessions(self):
        """flush() on a fresh summarizer with no adds must return immediately."""
        s = AsyncSessionSummarizer(llm=AsyncMock(), threshold=5)
        await s.flush()  # must not hang or raise


# ---------------------------------------------------------------------------
# DEFAULT_PROMPT content
# ---------------------------------------------------------------------------


class TestDefaultPrompt:
    def test_default_prompt_contains_actions_placeholder(self):
        """DEFAULT_PROMPT must have the {actions} placeholder the summarizer fills in."""
        assert "{actions}" in DEFAULT_PROMPT

    def test_default_prompt_is_non_empty_string(self):
        assert isinstance(DEFAULT_PROMPT, str)
        assert len(DEFAULT_PROMPT) > 50


# ---------------------------------------------------------------------------
# AsyncSessionSummarizer.active_sessions async property
# ---------------------------------------------------------------------------


class TestAsyncActiveSessions:
    @pytest.mark.asyncio
    async def test_active_sessions_returns_sessions_with_pending_actions(self):
        s = AsyncSessionSummarizer(llm=AsyncMock(return_value="s"), threshold=100)
        await s.add(_payload("alpha", n_actions=2))
        await s.add(_payload("beta", n_actions=1))
        # flush() waits until workers have processed every queued payload and
        # updated _counts, making the active_sessions check deterministic.
        await s.flush()

        sessions = await s.active_sessions
        assert "alpha" in sessions
        assert "beta" in sessions

    @pytest.mark.asyncio
    async def test_active_sessions_empty_before_any_add(self):
        s = AsyncSessionSummarizer(llm=AsyncMock(), threshold=10)
        assert await s.active_sessions == []

    @pytest.mark.asyncio
    async def test_active_sessions_empty_after_all_sessions_summarised(self):
        s = AsyncSessionSummarizer(llm=AsyncMock(return_value="summary"), threshold=1)
        await s.add(_payload("sess_x", n_actions=1))
        await s.flush()
        # After summarization counts are cleared.
        assert await s.active_sessions == []


# ---------------------------------------------------------------------------
# AsyncSessionSummarizer: bad prompt template (missing {actions})
# ---------------------------------------------------------------------------


class TestAsyncBadPromptTemplate:
    """Tests for the error path when the prompt template contains an unknown
    placeholder — ``{bad_key}`` causes ``str.format(actions=...)`` to raise
    ``KeyError``, which the summarizer catches and uses to restore history.

    Note: a template that simply *lacks* ``{actions}`` (e.g. "Summarise this.")
    does NOT raise — Python just ignores the unused kwarg.  A ``KeyError`` only
    fires when the template references a key that is not provided (e.g. ``{bad}``).
    """

    @pytest.mark.asyncio
    async def test_bad_template_restores_history_and_does_not_raise(self):
        """When the template raises KeyError, history must be restored."""
        s = AsyncSessionSummarizer(
            llm=AsyncMock(return_value="should not be called"),
            threshold=1,
            prompt="Context: {bad_key} — {actions}",  # {bad_key} → KeyError
        )
        payload = _payload("bad_sess", n_actions=1)
        await s.add(payload)
        await s.flush()

        # History must have been restored so no actions are lost.
        context = await s.get_context("bad_sess")
        assert context != ""

    @pytest.mark.asyncio
    async def test_bad_template_does_not_call_llm(self):
        """When the template raises KeyError, the LLM must not be called."""
        llm = AsyncMock(return_value="summary")
        s = AsyncSessionSummarizer(
            llm=llm,
            threshold=1,
            prompt="Context: {bad_key}",  # raises KeyError before LLM call
        )
        await s.add(_payload("t", n_actions=1))
        await s.flush()

        llm.assert_not_awaited()


# ---------------------------------------------------------------------------
# Item 2 — AsyncSessionSummarizer: bounded queue + idle-worker memory leak
# ---------------------------------------------------------------------------


class TestAsyncSummarizerBoundedQueue:
    @pytest.mark.asyncio
    async def test_queue_full_drop_fires_record_event_dropped(self):
        """When the per-session queue is full, add() must call record_event_dropped."""
        dropped_calls = []

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

        slow_llm_gate = asyncio.Event()

        async def slow_llm(prompt: str) -> str:
            await slow_llm_gate.wait()
            return "summary"

        # max_queue_size=1: first payload goes into the queue and is processed;
        # the second fills the queue; the third should be dropped.
        s = AsyncSessionSummarizer(
            llm=slow_llm,
            threshold=1,
            max_queue_size=1,
            metrics=MyMetrics(),
        )

        p1 = _payload("q1", n_actions=1)
        p2 = _payload("q1", n_actions=1)
        p3 = _payload("q1", n_actions=1)

        # First add starts the worker and begins processing (worker picks up p1).
        await s.add(p1)
        # Give worker a moment to dequeue p1 so the queue slot is free for p2.
        await asyncio.sleep(0.05)
        # p2 goes into the queue (queue now full again since worker is blocked).
        await s.add(p2)
        # p3 should be dropped because the queue is full.
        await s.add(p3)

        # Unblock the LLM so the test can clean up.
        slow_llm_gate.set()
        await s.flush()

        assert any(c["reason"] == "queue_full" for c in dropped_calls), (
            f"expected a drop call, got: {dropped_calls}"
        )

    @pytest.mark.asyncio
    async def test_idle_timeout_clears_history_and_counts(self):
        """After a worker idles out, _history and _counts for that session must be gone."""
        import asyncio as _asyncio
        from autoplay_sdk import summarizer as summarizer_mod

        original_timeout = summarizer_mod._WORKER_IDLE_TIMEOUT_S
        summarizer_mod._WORKER_IDLE_TIMEOUT_S = 0.05  # very short for the test
        try:
            s = AsyncSessionSummarizer(
                llm=AsyncMock(return_value="nope"),
                threshold=100,  # never reached — history stays in memory
            )
            await s.add(_payload("idle_sess", n_actions=1))
            await s.flush()  # wait until worker has processed the payload

            # Verify history is present before idle
            assert "idle_sess" in s._history or s._counts.get("idle_sess", 0) > 0

            # Wait for the worker to idle out and clean up
            await _asyncio.sleep(0.2)

            assert "idle_sess" not in s._history
            assert "idle_sess" not in s._counts
        finally:
            summarizer_mod._WORKER_IDLE_TIMEOUT_S = original_timeout


# ---------------------------------------------------------------------------
# Item 3 — SessionSummarizer (sync): LRU eviction
# ---------------------------------------------------------------------------


class TestSessionSummarizerMaxSessions:
    def test_lru_eviction_fires_when_max_sessions_exceeded(self):
        """The oldest session is evicted when max_sessions is exceeded."""
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"),
            threshold=100,  # never reached — keeps history in memory
            max_sessions=2,
        )
        s.add(_payload("alpha", n_actions=1))
        s.add(_payload("beta", n_actions=1))
        s.add(_payload("gamma", n_actions=1))  # evicts alpha

        # gamma and beta should still be tracked; alpha should be gone
        with s._lock:
            assert "gamma" in s._history
            assert "beta" in s._history
            assert "alpha" not in s._history
            assert "alpha" not in s._counts

    def test_evicted_session_history_and_counts_removed(self):
        """Evicted session leaves no trace in _history or _counts."""
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"),
            threshold=100,
            max_sessions=1,
        )
        s.add(_payload("first", n_actions=2))
        s.add(_payload("second", n_actions=1))  # evicts first

        with s._lock:
            assert "first" not in s._history
            assert "first" not in s._counts
            assert "second" in s._history

    def test_no_eviction_when_max_sessions_not_set(self):
        """Without max_sessions, all sessions are retained."""
        s = SessionSummarizer(
            llm=MagicMock(return_value="S"),
            threshold=100,
        )
        for i in range(10):
            s.add(_payload(f"sess_{i}", n_actions=1))

        with s._lock:
            assert len(s._history) == 10
