"""Tests for autoplay_sdk.rag — RagPipeline and AsyncRagPipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from autoplay_sdk.models import ActionsPayload, SlimAction, SummaryPayload
from autoplay_sdk.rag import AsyncRagPipeline, RagPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actions(session_id: str = "sess1") -> ActionsPayload:
    return ActionsPayload(
        product_id="p1",
        session_id=session_id,
        user_id="u1",
        email=None,
        actions=[
            SlimAction(
                title="Btn", description="Clicked Export", canonical_url="/export"
            )
        ],
        count=1,
        forwarded_at=0.0,
    )


def _summary(session_id: str = "sess1") -> SummaryPayload:
    return SummaryPayload(
        product_id="p1",
        session_id=session_id,
        summary="User exported a CSV.",
        replaces=3,
        forwarded_at=0.0,
    )


# ---------------------------------------------------------------------------
# RagPipeline (sync)
# ---------------------------------------------------------------------------


class TestRagPipeline:
    def test_on_actions_embeds_payload_text(self):
        embed = MagicMock(return_value=[0.1, 0.2])
        pipeline = RagPipeline(embed=embed, upsert=MagicMock())
        payload = _actions()
        pipeline.on_actions(payload)
        embed.assert_called_once_with(payload.to_text())

    def test_on_actions_upserts_with_session_id_vector_and_metadata(self):
        embed = MagicMock(return_value=[0.1, 0.2])
        upsert = MagicMock()
        pipeline = RagPipeline(embed=embed, upsert=upsert)
        pipeline.on_actions(_actions("sess42"))
        upsert.assert_called_once_with(
            "sess42:actions:0.0",
            [0.1, 0.2],
            {"session_id": "sess42", "type": "ActionsPayload", "forwarded_at": 0.0},
        )

    def test_on_summary_embeds_payload_text(self):
        embed = MagicMock(return_value=[0.3])
        pipeline = RagPipeline(embed=embed, upsert=MagicMock())
        payload = _summary()
        pipeline.on_summary(payload)
        embed.assert_called_once_with(payload.to_text())

    def test_on_summary_upserts_with_session_id_and_summary_type(self):
        embed = MagicMock(return_value=[0.3])
        upsert = MagicMock()
        pipeline = RagPipeline(embed=embed, upsert=upsert)
        pipeline.on_summary(_summary("sess99"))
        upsert.assert_called_once_with(
            "sess99:summary:0.0",
            [0.3],
            {"session_id": "sess99", "type": "SummaryPayload", "forwarded_at": 0.0},
        )

    def test_none_session_id_falls_back_to_unknown_as_upsert_id(self):
        embed = MagicMock(return_value=[0.1])
        upsert = MagicMock()
        pipeline = RagPipeline(embed=embed, upsert=upsert)
        payload = _actions()
        payload.session_id = None
        pipeline.on_actions(payload)
        assert upsert.call_args[0][0].startswith("unknown:actions:")

    def test_embed_exception_is_caught_and_does_not_raise(self):
        pipeline = RagPipeline(
            embed=MagicMock(side_effect=RuntimeError("embed failed")),
            upsert=MagicMock(),
        )
        pipeline.on_actions(_actions())  # must not raise

    def test_upsert_exception_is_caught_and_does_not_raise(self):
        pipeline = RagPipeline(
            embed=MagicMock(return_value=[0.1]),
            upsert=MagicMock(side_effect=RuntimeError("upsert failed")),
        )
        pipeline.on_actions(_actions())  # must not raise

    def test_with_summarizer_on_actions_delegates_to_summarizer_add(self):
        summarizer = MagicMock()
        embed = MagicMock()
        pipeline = RagPipeline(embed=embed, upsert=MagicMock(), summarizer=summarizer)
        payload = _actions()
        pipeline.on_actions(payload)
        summarizer.add.assert_called_once_with(payload)
        embed.assert_not_called()

    def test_with_summarizer_on_summary_is_wired_to_upsert_summary(self):
        summarizer = MagicMock()
        pipeline = RagPipeline(
            embed=MagicMock(return_value=[0.1]),
            upsert=MagicMock(),
            summarizer=summarizer,
        )
        assert summarizer.on_summary == pipeline._upsert_summary

    def test_upsert_summary_embeds_and_upserts_with_client_summary_type(self):
        embed = MagicMock(return_value=[0.5])
        upsert = MagicMock()
        pipeline = RagPipeline(embed=embed, upsert=upsert)
        pipeline._upsert_summary("sess_x", "A concise summary.")
        embed.assert_called_once_with("A concise summary.")
        upsert.assert_called_once_with(
            "sess_x:client-summary",
            [0.5],
            {"session_id": "sess_x", "type": "ClientSummary"},
        )

    def test_upsert_summary_exception_does_not_raise(self):
        pipeline = RagPipeline(
            embed=MagicMock(side_effect=RuntimeError("boom")),
            upsert=MagicMock(),
        )
        pipeline._upsert_summary("s", "text")  # must not raise


# ---------------------------------------------------------------------------
# AsyncRagPipeline
# ---------------------------------------------------------------------------


class TestAsyncRagPipeline:
    @pytest.mark.asyncio
    async def test_on_actions_awaits_embed_and_upsert(self):
        embed = AsyncMock(return_value=[0.1, 0.2])
        upsert = AsyncMock()
        pipeline = AsyncRagPipeline(embed=embed, upsert=upsert)
        payload = _actions("async_sess")
        await pipeline.on_actions(payload)
        embed.assert_awaited_once_with(payload.to_text())
        upsert.assert_awaited_once_with(
            "async_sess:actions:0.0",
            [0.1, 0.2],
            {"session_id": "async_sess", "type": "ActionsPayload", "forwarded_at": 0.0},
        )

    @pytest.mark.asyncio
    async def test_on_summary_awaits_embed_and_upsert(self):
        embed = AsyncMock(return_value=[0.9])
        upsert = AsyncMock()
        pipeline = AsyncRagPipeline(embed=embed, upsert=upsert)
        payload = _summary("async_sess")
        await pipeline.on_summary(payload)
        embed.assert_awaited_once_with(payload.to_text())
        upsert.assert_awaited_once_with(
            "async_sess:summary:0.0",
            [0.9],
            {"session_id": "async_sess", "type": "SummaryPayload", "forwarded_at": 0.0},
        )

    @pytest.mark.asyncio
    async def test_none_session_id_falls_back_to_unknown(self):
        embed = AsyncMock(return_value=[0.1])
        upsert = AsyncMock()
        pipeline = AsyncRagPipeline(embed=embed, upsert=upsert)
        payload = _actions()
        payload.session_id = None
        await pipeline.on_actions(payload)
        assert upsert.call_args[0][0].startswith("unknown:actions:")

    @pytest.mark.asyncio
    async def test_embed_exception_is_caught_and_does_not_raise(self):
        pipeline = AsyncRagPipeline(
            embed=AsyncMock(side_effect=RuntimeError("embed exploded")),
            upsert=AsyncMock(),
        )
        await pipeline.on_actions(_actions())  # must not raise

    @pytest.mark.asyncio
    async def test_upsert_exception_is_caught_and_does_not_raise(self):
        pipeline = AsyncRagPipeline(
            embed=AsyncMock(return_value=[0.1]),
            upsert=AsyncMock(side_effect=RuntimeError("upsert exploded")),
        )
        await pipeline.on_actions(_actions())  # must not raise

    @pytest.mark.asyncio
    async def test_with_summarizer_on_actions_delegates_to_summarizer(self):
        summarizer = MagicMock()
        summarizer.add = AsyncMock()
        embed = AsyncMock()
        pipeline = AsyncRagPipeline(
            embed=embed, upsert=AsyncMock(), summarizer=summarizer
        )
        payload = _actions()
        await pipeline.on_actions(payload)
        summarizer.add.assert_awaited_once_with(payload)
        embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_summary_embeds_and_upserts_with_client_summary_type(self):
        embed = AsyncMock(return_value=[0.7])
        upsert = AsyncMock()
        pipeline = AsyncRagPipeline(embed=embed, upsert=upsert)
        await pipeline._upsert_summary("sess_async", "Async summary text.")
        embed.assert_awaited_once_with("Async summary text.")
        upsert.assert_awaited_once_with(
            "sess_async:client-summary",
            [0.7],
            {"session_id": "sess_async", "type": "ClientSummary"},
        )

    @pytest.mark.asyncio
    async def test_upsert_summary_exception_does_not_raise(self):
        pipeline = AsyncRagPipeline(
            embed=AsyncMock(side_effect=RuntimeError("boom")),
            upsert=AsyncMock(),
        )
        await pipeline._upsert_summary("s", "text")  # must not raise

    @pytest.mark.asyncio
    async def test_with_summarizer_on_summary_is_wired_to_upsert_summary(self):
        """Mirrors the sync RagPipeline test: summarizer.on_summary must point to
        the pipeline's _upsert_summary so client-generated summaries are embedded
        and upserted automatically."""
        summarizer = MagicMock()
        summarizer.on_summary = None
        pipeline = AsyncRagPipeline(
            embed=AsyncMock(), upsert=AsyncMock(), summarizer=summarizer
        )
        assert summarizer.on_summary == pipeline._upsert_summary
