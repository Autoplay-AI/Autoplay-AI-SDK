"""Tests for autoplay_sdk.chatbot — BaseChatbotWriter delivery policy."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from autoplay_sdk.chatbot import BaseChatbotWriter, format_chatbot_note_header


# ---------------------------------------------------------------------------
# Minimal concrete subclass
# ---------------------------------------------------------------------------


class _TestChatbot(BaseChatbotWriter):
    """Minimal subclass: stubs out platform API calls with AsyncMock."""

    def __init__(self, **kwargs):
        super().__init__(product_id="test_product", **kwargs)
        self._post_note = AsyncMock(return_value="part-001")
        self._redact_part = AsyncMock(return_value=None)


def _action(
    index: int = 0, ts: float | None = None, description: str = "Did something"
) -> dict:
    """Build a slim_action dict."""
    return {
        "index": index,
        "description": description,
        "timestamp_start": ts if ts is not None else time.time(),
    }


# ---------------------------------------------------------------------------
# TestPreLinkBuffering
# ---------------------------------------------------------------------------


class TestPreLinkBuffering:
    """write_actions before on_session_linked — buffer only, no API calls."""

    def test_buffers_actions_returns_none(self):
        chatbot = _TestChatbot()
        result = asyncio.run(
            chatbot.write_actions("", "sess1", [_action(0), _action(1)])
        )
        assert result is None
        chatbot._post_note.assert_not_called()

    def test_actions_accumulate_in_pending(self):
        chatbot = _TestChatbot()
        asyncio.run(chatbot.write_actions("", "sess1", [_action(0)]))
        asyncio.run(chatbot.write_actions("", "sess1", [_action(1)]))
        assert len(chatbot._pending["sess1"]) == 2

    def test_empty_slim_actions_is_noop(self):
        chatbot = _TestChatbot()
        result = asyncio.run(chatbot.write_actions("", "sess1", []))
        assert result is None
        assert "sess1" not in chatbot._pending
        chatbot._post_note.assert_not_called()

    def test_sliding_window_eviction(self):
        chatbot = _TestChatbot(pre_link_window_s=1.0)
        old_ts = time.time() - 10.0  # 10s ago — well beyond the 1s window
        asyncio.run(chatbot.write_actions("", "sess1", [_action(0, ts=old_ts)]))

        # Add a fresh action — this triggers the eviction pass
        asyncio.run(chatbot.write_actions("", "sess1", [_action(1)]))

        remaining = chatbot._pending["sess1"]
        assert len(remaining) == 1
        assert remaining[0]["index"] == 1

    def test_no_post_note_before_link(self):
        chatbot = _TestChatbot()
        for i in range(5):
            asyncio.run(chatbot.write_actions("", "sess1", [_action(i)]))
        chatbot._post_note.assert_not_called()


# ---------------------------------------------------------------------------
# TestAtLinkFlush
# ---------------------------------------------------------------------------


class TestAtLinkFlush:
    """on_session_linked — flush pre-link buffer as a single _post_note call."""

    @pytest.mark.asyncio
    async def test_flushes_buffer_as_one_note(self):
        chatbot = _TestChatbot()
        await chatbot.write_actions("", "sess1", [_action(0), _action(1)])
        await chatbot.on_session_linked("sess1", "conv-123")

        chatbot._post_note.assert_called_once()
        args = chatbot._post_note.call_args
        assert args[0][0] == "conv-123"

    @pytest.mark.asyncio
    async def test_buffer_cleared_after_flush(self):
        chatbot = _TestChatbot()
        await chatbot.write_actions("", "sess1", [_action(0)])
        await chatbot.on_session_linked("sess1", "conv-123")

        assert chatbot._pending.get("sess1", []) == []

    @pytest.mark.asyncio
    async def test_no_post_note_when_buffer_empty(self):
        chatbot = _TestChatbot()
        # Link with nothing pre-buffered
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.assert_not_called()

    @pytest.mark.asyncio
    async def test_inflight_debounce_task_cancelled_on_link(self):
        """A race: write_actions called twice, then linked — old task cancelled."""
        chatbot = _TestChatbot(
            post_link_debounce_s=10.0
        )  # long window so it doesn't fire

        # First link to get a conv_id, then write to create a debounce task
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()

        await chatbot.write_actions("", "sess1", [_action(0)])

        # Simulate a second link (edge case — same session re-linked)
        await chatbot.on_session_linked("sess1", "conv-456")

        # The inflight debounce task from before re-link should be cancelled
        task = chatbot._debounce_tasks.get("sess1")
        assert task is None or task.done()

    @pytest.mark.asyncio
    async def test_part_id_stored_after_flush(self):
        chatbot = _TestChatbot()
        chatbot._post_note.return_value = "part-flush"
        await chatbot.write_actions("", "sess1", [_action(0)])
        await chatbot.on_session_linked("sess1", "conv-123")

        assert "part-flush" in chatbot._part_ids["sess1"]


# ---------------------------------------------------------------------------
# TestPostLinkDebounce
# ---------------------------------------------------------------------------


class TestPostLinkDebounce:
    """write_actions after on_session_linked — debounce to one _post_note call."""

    @pytest.mark.asyncio
    async def test_single_write_fires_after_debounce(self):
        chatbot = _TestChatbot(post_link_debounce_s=0.005)
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()

        await chatbot.write_actions("", "sess1", [_action(0)])
        await asyncio.sleep(0.02)

        chatbot._post_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_rapid_writes_coalesce_into_one_note(self):
        chatbot = _TestChatbot(post_link_debounce_s=0.005)
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()

        await chatbot.write_actions("", "sess1", [_action(0)])
        await chatbot.write_actions("", "sess1", [_action(1)])
        await chatbot.write_actions("", "sess1", [_action(2)])
        await asyncio.sleep(0.02)

        # All three writes should be coalesced into exactly one note
        chatbot._post_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_coalesced_actions_appear_in_note(self):
        chatbot = _TestChatbot(post_link_debounce_s=0.005)
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()

        await chatbot.write_actions("", "sess1", [_action(0, description="First")])
        await chatbot.write_actions("", "sess1", [_action(1, description="Second")])
        await asyncio.sleep(0.02)

        note_body = chatbot._post_note.call_args[0][1]
        assert "First" in note_body
        assert "Second" in note_body

    @pytest.mark.asyncio
    async def test_post_note_not_called_before_debounce_expires(self):
        chatbot = _TestChatbot(post_link_debounce_s=10.0)
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()

        await chatbot.write_actions("", "sess1", [_action(0)])
        # Do NOT sleep — task still pending
        chatbot._post_note.assert_not_called()

    @pytest.mark.asyncio
    async def test_part_id_stored_after_debounce_fires(self):
        chatbot = _TestChatbot(post_link_debounce_s=0.005)
        chatbot._post_note.return_value = "part-debounce"
        await chatbot.on_session_linked("sess1", "conv-123")
        chatbot._post_note.reset_mock()
        chatbot._post_note.return_value = "part-debounce"

        await chatbot.write_actions("", "sess1", [_action(0)])
        await asyncio.sleep(0.02)

        assert "part-debounce" in chatbot._part_ids["sess1"]


# ---------------------------------------------------------------------------
# TestFormatNote
# ---------------------------------------------------------------------------


class TestFormatNote:
    """_format_note — note formatting: header, binning, no-binning."""

    def test_header_contains_session_id(self):
        chatbot = _TestChatbot()
        note = chatbot._format_note("sess-abc", [_action(0)])
        lines = note.splitlines()
        assert lines[0] == "session_id: sess-abc"

    def test_header_contains_utc_timestamp(self):
        chatbot = _TestChatbot()
        note = chatbot._format_note("sess1", [_action(0)])
        lines = note.splitlines()
        assert lines[1].startswith("timestamp:")
        assert "UTC" in lines[1]

    def test_binning_inserts_blank_lines_between_bins(self):
        chatbot = _TestChatbot(bin_seconds=3)
        t0 = 1000.0
        actions = [
            _action(0, ts=t0, description="Early"),
            _action(1, ts=t0 + 5.0, description="Late"),  # different 3s bin
        ]
        note = chatbot._format_note("sess1", actions, bin_seconds=3)
        # blank line should appear between the two bin groups
        assert "\n\n" in note

    def test_no_binning_produces_no_blank_separator_between_actions(self):
        chatbot = _TestChatbot(bin_seconds=3)
        t0 = 1000.0
        actions = [
            _action(0, ts=t0, description="Early"),
            _action(1, ts=t0 + 5.0, description="Late"),
        ]
        note = chatbot._format_note("sess1", actions, bin_seconds=0)
        action_lines = [line for line in note.splitlines() if line.startswith("[")]
        # Should be exactly two consecutive action lines (no blank between them)
        assert len(action_lines) == 2

    def test_actions_appear_in_order(self):
        chatbot = _TestChatbot()
        t0 = 1000.0
        actions = [
            _action(0, ts=t0, description="First action"),
            _action(1, ts=t0 + 1.0, description="Second action"),
            _action(2, ts=t0 + 2.0, description="Third action"),
        ]
        note = chatbot._format_note("sess1", actions, bin_seconds=0)
        idx_first = note.index("First action")
        idx_second = note.index("Second action")
        idx_third = note.index("Third action")
        assert idx_first < idx_second < idx_third

    def test_display_index_is_one_based_ignores_wire_index(self):
        chatbot = _TestChatbot()
        note = chatbot._format_note("sess1", [_action(42, description="Click")])
        assert "[1]" in note
        assert "[42]" not in note

    def test_multiple_actions_with_wire_index_zero_numbered_sequentially(self):
        chatbot = _TestChatbot()
        t0 = 1000.0
        actions = [
            _action(0, ts=t0 + 1.0, description="Second"),
            _action(0, ts=t0, description="First"),
        ]
        note = chatbot._format_note("sess1", actions, bin_seconds=0)
        assert "[1] First" in note
        assert "[2] Second" in note

    def test_empty_actions_note_header_only(self):
        chatbot = _TestChatbot()
        note = chatbot._format_note("sess1", [])
        lines = [ln for ln in note.splitlines() if ln.strip()]
        assert lines[0] == "session_id: sess1"
        assert lines[1].startswith("timestamp:")


class TestFormatChatbotNoteHeader:
    def test_known_session_and_timestamp(self):
        text = format_chatbot_note_header("sid-1", 1_700_000_000.0)
        assert text.startswith("session_id: sid-1\n")
        assert "timestamp:" in text
        assert text.endswith("\n\n")
