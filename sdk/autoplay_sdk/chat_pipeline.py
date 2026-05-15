"""autoplay_sdk.chat_pipeline — safe composition helpers for chat integrations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from autoplay_sdk.agent_context import AsyncAgentContextWriter
from autoplay_sdk.context_store import AsyncContextStore
from autoplay_sdk.models import ActionsPayload
from autoplay_sdk.summarizer import AsyncSessionSummarizer


@dataclass
class AsyncChatPipeline:
    """Container for composed async chat primitives."""

    summarizer: AsyncSessionSummarizer
    context_store: AsyncContextStore
    agent_writer: AsyncAgentContextWriter

    async def on_actions(self, payload: ActionsPayload) -> None:
        """Canonical callback order: ContextStore first, writer second."""
        await self.context_store.add(payload)
        await self.agent_writer.add(payload)


def compose_chat_pipeline(
    *,
    llm: Callable[[str], Awaitable[str]],
    threshold: int = 10,
    lookback_seconds: float | None = 300.0,
    max_actions: int | None = 20,
    write_actions: Callable[[str, str], Awaitable[None]] | None = None,
    overwrite_with_summary: Callable[[str, str], Awaitable[None]] | None = None,
    debounce_ms: int = 0,
) -> AsyncChatPipeline:
    """Wire summarizer + context store + agent writer without callback clobbering."""

    async def _noop_overwrite(_session_id: str, _summary: str) -> None:
        return

    summarizer = AsyncSessionSummarizer(llm=llm, threshold=threshold)
    context_store = AsyncContextStore(
        summarizer=None,
        lookback_seconds=lookback_seconds,
        max_actions=max_actions,
    )
    agent_writer = AsyncAgentContextWriter(
        summarizer=summarizer,
        write_actions=write_actions,
        overwrite_with_summary=overwrite_with_summary or _noop_overwrite,
        debounce_ms=debounce_ms,
    )

    writer_on_summary = summarizer.on_summary

    async def _fanout_summary(session_id: str, summary_text: str) -> None:
        await context_store.on_summary(session_id, summary_text)
        if writer_on_summary is not None:
            await writer_on_summary(session_id, summary_text)

    summarizer.on_summary = _fanout_summary

    return AsyncChatPipeline(
        summarizer=summarizer,
        context_store=context_store,
        agent_writer=agent_writer,
    )


__all__ = ["AsyncChatPipeline", "compose_chat_pipeline"]
