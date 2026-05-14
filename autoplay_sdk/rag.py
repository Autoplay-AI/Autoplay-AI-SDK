"""autoplay_sdk.rag — Plug-and-play RAG pipeline wiring.

Connects the Autoplay real-time event stream to any embedding model and any
vector store.  You provide two callables — ``embed`` and ``upsert`` — and the
pipeline handles the rest.

Sync usage (blocking embed + upsert)::

    import openai
    from autoplay_sdk import ConnectorClient
    from autoplay_sdk.rag import RagPipeline

    openai_client = openai.OpenAI()

    pipeline = RagPipeline(
        embed=lambda text: openai_client.embeddings.create(
            input=text, model="text-embedding-3-small"
        ).data[0].embedding,
        upsert=lambda id, vector, meta: index.upsert([(id, vector, meta)]),
    )

    ConnectorClient(url=URL, token=TOKEN) \\
        .on_actions(pipeline.on_actions) \\
        .on_summary(pipeline.on_summary) \\
        .run()

Async usage (awaitable embed + upsert)::

    import openai
    from autoplay_sdk import AsyncConnectorClient
    from autoplay_sdk.rag import AsyncRagPipeline

    openai_client = openai.AsyncOpenAI()

    async def embed(text):
        r = await openai_client.embeddings.create(input=text, model="text-embedding-3-small")
        return r.data[0].embedding

    async def upsert(id, vector, meta):
        await index.upsert([(id, vector, meta)])

    pipeline = AsyncRagPipeline(embed=embed, upsert=upsert)

    async with AsyncConnectorClient(url=URL, token=TOKEN) as client:
        client.on_actions(pipeline.on_actions)
        client.on_summary(pipeline.on_summary)
        await client.run()

With a SessionSummarizer for context-window management::

    from autoplay_sdk.rag import RagPipeline
    from autoplay_sdk.summarizer import SessionSummarizer

    summarizer = SessionSummarizer(llm=my_llm_fn, threshold=10)
    pipeline   = RagPipeline(embed=embed_fn, upsert=upsert_fn, summarizer=summarizer)

    client.on_actions(pipeline.on_actions).on_summary(pipeline.on_summary).run()
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from autoplay_sdk.exceptions import SdkConfigError
from autoplay_sdk.models import ActionsPayload, SummaryPayload

logger = logging.getLogger(__name__)


class RagPipeline:
    """Synchronous RAG pipeline: embed events and upsert into a vector store.

    Designed to be wired directly to ``ConnectorClient`` callbacks::

        pipeline = RagPipeline(embed=embed_fn, upsert=upsert_fn)
        client.on_actions(pipeline.on_actions).on_summary(pipeline.on_summary)

    Args:
        embed:      ``(text: str) -> list[float]`` — any embedding function.
                    Called with ``payload.to_text()`` for each event.
        upsert:     ``(id: str, vector: list[float], metadata: dict) -> None``
                    — writes the embedding to your vector store.
        summarizer: Optional ``SessionSummarizer``.  When provided, actions
                    are first passed through the summarizer; the summarizer's
                    ``on_summary`` output is then embedded and upserted.
                    Pass ``None`` to embed raw action batches directly.
    """

    def __init__(
        self,
        embed: Callable[[str], list[float]],
        upsert: Callable[[str, list[float], dict], None],
        summarizer: Any | None = None,
    ) -> None:
        if not callable(embed):
            raise SdkConfigError(f"embed must be callable, got {type(embed)!r}")
        if not callable(upsert):
            raise SdkConfigError(f"upsert must be callable, got {type(upsert)!r}")
        self._embed = embed
        self._upsert = upsert
        self._summarizer = summarizer

        if summarizer is not None:
            if summarizer.on_summary is not None:
                logger.warning(
                    "RagPipeline: replacing existing on_summary on the provided summarizer; "
                    "the previous callback will no longer be called.",
                )
            summarizer.on_summary = self._upsert_summary

    # ------------------------------------------------------------------
    # Callbacks — wire these to ConnectorClient
    # ------------------------------------------------------------------

    def on_actions(self, payload: ActionsPayload) -> None:
        """Process an incoming actions batch.

        If a ``SessionSummarizer`` is attached, the payload is passed through
        it first; embedding and upserting happen when the summarizer threshold
        is reached (not immediately).  This keeps your vector store compact —
        one summary vector per session rather than one vector per action batch.

        If no summarizer is configured, the batch is embedded and upserted
        immediately.

        Wire to ``ConnectorClient``::

            client.on_actions(pipeline.on_actions)

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        if self._summarizer is not None:
            self._summarizer.add(payload)
        else:
            self._embed_and_upsert(payload)

    def on_summary(self, payload: SummaryPayload) -> None:
        """Process a server-side summary event from the connector.

        Embeds the prose summary text and upserts it to the vector store.
        Use this when the connector itself is configured to produce server-side
        summaries (as opposed to using a client-side ``SessionSummarizer``).

        Wire to ``ConnectorClient``::

            client.on_summary(pipeline.on_summary)

        Args:
            payload: Typed ``SummaryPayload`` from the event stream.
        """
        self._embed_and_upsert(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _embed_and_upsert(self, payload: ActionsPayload | SummaryPayload) -> None:
        text = payload.to_text()
        session_id = payload.session_id or "unknown"
        payload_type = "actions" if isinstance(payload, ActionsPayload) else "summary"
        vector_id = f"{session_id}:{payload_type}:{payload.forwarded_at}"
        try:
            vector = self._embed(text)
        except Exception as exc:
            logger.error(
                "rag: embed failed for id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )
            return
        try:
            self._upsert(
                vector_id,
                vector,
                {
                    "session_id": session_id,  # normalized "unknown" instead of None
                    "type": type(payload).__name__,
                    "forwarded_at": payload.forwarded_at,
                },
            )
            logger.debug(
                "rag: upserted id=%s",
                vector_id,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )
        except Exception as exc:
            logger.error(
                "rag: upsert failed for id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )

    def _upsert_summary(self, session_id: str, summary_text: str) -> None:
        """Called by SessionSummarizer when a client-side summary is ready.

        Uses a rolling vector ID (``{session_id}:client-summary``) so each new
        summary overwrites the previous one for the same session — intentional,
        since the summary represents the latest condensed context window.
        """
        vector_id = f"{session_id}:client-summary"
        try:
            vector = self._embed(summary_text)
        except Exception as exc:
            logger.error(
                "rag: embed failed for client summary id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={"vector_id": vector_id, "session_id": session_id},
            )
            return
        try:
            self._upsert(
                vector_id, vector, {"session_id": session_id, "type": "ClientSummary"}
            )
            logger.debug(
                "rag: upserted client summary id=%s",
                vector_id,
                extra={"vector_id": vector_id, "session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "rag: upsert failed for client summary id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={"vector_id": vector_id, "session_id": session_id},
            )


class AsyncRagPipeline:
    """Async RAG pipeline for use with ``AsyncConnectorClient``.

    Identical interface to ``RagPipeline`` but ``embed`` and ``upsert`` are
    async callables (coroutines)::

        pipeline = AsyncRagPipeline(embed=async_embed_fn, upsert=async_upsert_fn)
        client.on_actions(pipeline.on_actions).on_summary(pipeline.on_summary)
        await client.run()

    Args:
        embed:      ``async (text: str) -> list[float]``
        upsert:     ``async (id: str, vector: list[float], metadata: dict) -> None``
        summarizer: Optional ``AsyncSessionSummarizer``.
    """

    def __init__(
        self,
        embed: Callable[[str], Any],
        upsert: Callable[[str, list[float], dict], Any],
        summarizer: Any | None = None,
    ) -> None:
        if not callable(embed):
            raise SdkConfigError(f"embed must be callable, got {type(embed)!r}")
        if not callable(upsert):
            raise SdkConfigError(f"upsert must be callable, got {type(upsert)!r}")
        self._embed = embed
        self._upsert = upsert
        self._summarizer = summarizer

        if summarizer is not None:
            if summarizer.on_summary is not None:
                logger.warning(
                    "AsyncRagPipeline: replacing existing on_summary on the provided summarizer; "
                    "the previous callback will no longer be called.",
                )
            summarizer.on_summary = self._upsert_summary

    # ------------------------------------------------------------------
    # Async callbacks
    # ------------------------------------------------------------------

    async def on_actions(self, payload: ActionsPayload) -> None:
        """Process an incoming actions batch.

        Awaits ``embed`` and ``upsert``.  If an ``AsyncSessionSummarizer`` is
        attached, the payload is queued to the summarizer's per-session worker
        and returns immediately — embedding happens in the background when the
        threshold is reached.

        Wire to ``AsyncConnectorClient``::

            client.on_actions(pipeline.on_actions)

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        if self._summarizer is not None:
            await self._summarizer.add(payload)
        else:
            await self._embed_and_upsert(payload)

    async def on_summary(self, payload: SummaryPayload) -> None:
        """Process a server-side summary event from the connector.

        Awaits ``embed`` and ``upsert`` on the prose summary text.

        Wire to ``AsyncConnectorClient``::

            client.on_summary(pipeline.on_summary)

        Args:
            payload: Typed ``SummaryPayload`` from the event stream.
        """
        await self._embed_and_upsert(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _embed_and_upsert(self, payload: ActionsPayload | SummaryPayload) -> None:
        session_id = payload.session_id or "unknown"
        payload_type = "actions" if isinstance(payload, ActionsPayload) else "summary"
        vector_id = f"{session_id}:{payload_type}:{payload.forwarded_at}"
        try:
            vector = await self._embed(payload.to_text())
        except Exception as exc:
            logger.error(
                "rag: embed failed for id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )
            return
        try:
            await self._upsert(
                vector_id,
                vector,
                {
                    "session_id": session_id,  # normalized "unknown" instead of None
                    "type": type(payload).__name__,
                    "forwarded_at": payload.forwarded_at,
                },
            )
            logger.debug(
                "rag: upserted id=%s",
                vector_id,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )
        except Exception as exc:
            logger.error(
                "rag: upsert failed for id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={
                    "vector_id": vector_id,
                    "session_id": session_id,
                    "event_type": payload_type,
                    "product_id": getattr(payload, "product_id", None),
                },
            )

    async def _upsert_summary(self, session_id: str, summary_text: str) -> None:
        """Called by AsyncSessionSummarizer when a client-side summary is ready.

        Uses a rolling vector ID (``{session_id}:client-summary``) so each new
        summary overwrites the previous one for the same session — intentional,
        since the summary represents the latest condensed context window.
        """
        vector_id = f"{session_id}:client-summary"
        try:
            vector = await self._embed(summary_text)
        except Exception as exc:
            logger.error(
                "rag: embed failed for client summary id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={"vector_id": vector_id, "session_id": session_id},
            )
            return
        try:
            await self._upsert(
                vector_id, vector, {"session_id": session_id, "type": "ClientSummary"}
            )
            logger.debug(
                "rag: upserted client summary id=%s",
                vector_id,
                extra={"vector_id": vector_id, "session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "rag: upsert failed for client summary id=%s: %s",
                vector_id,
                exc,
                exc_info=True,
                extra={"vector_id": vector_id, "session_id": session_id},
            )
