"""autoplay_sdk.agent_context — Push real-time event context to any agent destination.

``AsyncAgentContextWriter`` implements a **push model** for keeping an agent's
context window current and bounded.  Raw UI actions are streamed to your chosen
destination as they arrive.  When enough accumulate, an ``AsyncSessionSummarizer``
produces an LLM summary and the class calls your ``overwrite_with_summary``
callback to replace the raw actions at the destination with the condensed version.

This is the same pipeline used internally by the event connector's Intercom
integration:

    write_actions  →  action note posted to Intercom conversation
    ...K actions   →  LLM summary produced (via AsyncSessionSummarizer)
    summary first  →  summary note posted to Intercom
    redact after   →  old action notes blanked via Intercom redact API

Ordering guarantee (critical)
------------------------------
The summary must be **confirmed at the destination** before any previous context
is removed.  This prevents any window in which the agent has a blank context::

    async def overwrite_with_summary(session_id: str, summary: str) -> None:
        # 1. Post the summary — agent has context during the whole swap.
        await destination.post_note(conv_id, summary)
        # 2. Only now remove the raw-action notes.
        await destination.redact_parts(conv_id, old_part_ids)

If step 2 fails the summary is still visible and the agent is never left empty.
This contract applies to any ``ConversationWriter`` backend, not just Intercom.
See ``autoplay_sdk.chatbot.BaseChatbotWriter`` for a base class that handles the
pre/post-link delivery routing while you implement only ``_post_note`` and
``_redact_part``.

Usage (generic chatbot)::

    import openai
    from autoplay_sdk import AsyncConnectorClient, AsyncSessionSummarizer
    from autoplay_sdk.agent_context import AsyncAgentContextWriter

    async_openai = openai.AsyncOpenAI()

    async def my_llm(prompt: str) -> str:
        r = await async_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content

    summarizer = AsyncSessionSummarizer(llm=my_llm, threshold=10)

    async def write_actions(session_id: str, text: str) -> None:
        await chatbot.set_context(session_id, text)

    async def overwrite_with_summary(session_id: str, summary: str) -> None:
        # Post the summary FIRST — agent has context during the whole operation.
        await chatbot.set_context(session_id, summary)
        # Only now clear the accumulated raw actions from wherever you stored them.

    writer = AsyncAgentContextWriter(
        summarizer=summarizer,
        overwrite_with_summary=overwrite_with_summary,
        write_actions=write_actions,
    )

    async with AsyncConnectorClient(url=URL, token=TOKEN) as client:
        client.on_actions(writer.add)
        await client.run()

Usage (Intercom)::

    from collections import defaultdict

    part_ids: dict[str, list[str]] = defaultdict(list)

    async def write_actions(session_id: str, text: str) -> None:
        conv_id = conv_map[session_id]
        part_id = await intercom.post_note(conv_id, text)
        part_ids[session_id].append(part_id)

    async def overwrite_with_summary(session_id: str, summary: str) -> None:
        conv_id = conv_map[session_id]
        # Post summary FIRST — Intercom users see uninterrupted context.
        await intercom.post_note(conv_id, summary)
        # Redact old action notes only after the summary is confirmed.
        old = part_ids.pop(session_id, [])
        await intercom.redact_parts(conv_id, old)

    writer = AsyncAgentContextWriter(
        summarizer=summarizer,
        overwrite_with_summary=overwrite_with_summary,
        write_actions=write_actions,
    )
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from autoplay_sdk.models import ActionsPayload
from autoplay_sdk.summarizer import AsyncSessionSummarizer

logger = logging.getLogger(__name__)


class AsyncAgentContextWriter:
    """Push real-time event context to any agent, overwriting with LLM summaries.

    ``AsyncAgentContextWriter`` wraps an ``AsyncSessionSummarizer`` and two
    user-provided callbacks to implement the push-and-overwrite pattern:

    1. Each ``ActionsPayload`` is formatted and forwarded to ``write_actions``
       (optional) so the destination stays up-to-date in real time.
    2. The payload is handed to the ``AsyncSessionSummarizer``.  When the
       configured action threshold is reached, the summarizer calls the LLM,
       produces a condensed summary, and invokes ``_on_summary``.
    3. ``_on_summary`` calls ``overwrite_with_summary`` (required), which must
       replace the previous raw-action context at the destination with the
       summary.

    **Ordering guarantee** — ``overwrite_with_summary`` is called and awaited
    to completion before any previous context should be removed.  Implement
    the callback so the summary is posted to the destination first; only once
    that succeeds should the old context be deleted or redacted.  This mirrors
    the Intercom integration's ``write_summary → pre_write_summary`` ordering
    and ensures the agent is never left with a blank context window.

    Args:
        summarizer:             ``AsyncSessionSummarizer`` instance (LLM, threshold,
                                and prompt are all configured on it).  Required — the
                                LLM step is what makes the overwrite safe to perform.
        overwrite_with_summary: ``async (session_id, summary_text) -> None``.
                                Called after LLM summarisation.  Must post the summary
                                to the destination before removing any prior context.
        write_actions:          ``async (session_id, text) -> None`` (optional).
                                Called on every new batch so the destination has the
                                freshest raw actions between summarisations.
        debounce_ms:            Per-session trailing-edge accumulation window in
                                milliseconds.  When ``> 0``, multiple ``add()`` calls
                                arriving within the window are merged into one
                                ``ActionsPayload`` before ``write_actions`` is called,
                                reducing destination API calls when events burst.
                                ``0`` (default) disables debouncing — every ``add()``
                                dispatches immediately, preserving the existing
                                behaviour.

                                Note: set ``debounce_ms=0`` (the default) if your
                                ``write_actions`` callback already coalesces
                                internally — for example, a ``BaseChatbotWriter``
                                subclass that applies its own ``post_link_debounce_s``
                                window.  Stacking both windows adds latency without
                                further reducing API calls.
    """

    def __init__(
        self,
        summarizer: AsyncSessionSummarizer,
        overwrite_with_summary: Callable[[str, str], Awaitable[None]],
        write_actions: Callable[[str, str], Awaitable[None]] | None = None,
        debounce_ms: int = 0,
    ) -> None:
        self._summarizer = summarizer
        self._overwrite_with_summary = overwrite_with_summary
        self._write_actions = write_actions
        self._debounce_s: float = debounce_ms / 1000.0

        # Debounce state — only allocated when debouncing is enabled.
        if self._debounce_s > 0:
            self._pending: dict[str, list[ActionsPayload]] = defaultdict(list)
            self._handles: dict[str, asyncio.TimerHandle] = {}
            self._loop: asyncio.AbstractEventLoop | None = None

        # Hook into the summarizer so _on_summary is called after each LLM pass.
        if self._summarizer.on_summary is not None:
            logger.warning(
                "agent_context: AsyncAgentContextWriter is overwriting an existing "
                "on_summary callback on the provided AsyncSessionSummarizer. "
                "The previous callback (%r) will no longer be called.",
                self._summarizer.on_summary,
            )
        self._summarizer.on_summary = self._on_summary

    async def add(self, payload: ActionsPayload) -> None:
        """Receive an actions batch, forward it, and feed it to the summarizer.

        When ``debounce_ms == 0`` (default), calls ``write_actions`` immediately
        and hands the payload to the ``AsyncSessionSummarizer``.

        When ``debounce_ms > 0``, accumulates the payload in a per-session
        buffer and (re)schedules a trailing-edge timer.  When the timer fires
        with no new arrivals, all pending payloads for the session are merged
        via ``ActionsPayload.merge()`` and dispatched as a single
        ``write_actions`` call.  The summarizer always receives the merged
        payload, so threshold counting is unaffected.

        Wire directly to ``on_actions``::

            client.on_actions(writer.add)

        Args:
            payload: Typed ``ActionsPayload`` from the event stream.
        """
        if self._debounce_s > 0:
            session_id = payload.session_id or "unknown"
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            self._pending[session_id].append(payload)
            old = self._handles.pop(session_id, None)
            if old is not None:
                old.cancel()
            self._handles[session_id] = self._loop.call_later(
                self._debounce_s, self._flush_session, session_id
            )
        else:
            await self._deliver(payload)

    def _flush_session(self, session_id: str) -> None:
        """Synchronous ``call_later`` callback — merges pending payloads and dispatches.

        Called by the event loop after the debounce window expires with no new
        arrivals for ``session_id``.  Creates a fire-and-forget task that runs
        ``_deliver`` with the merged payload.

        Args:
            session_id: The session whose pending payloads should be flushed.
        """
        self._handles.pop(session_id, None)
        payloads = list(self._pending.pop(session_id, []))
        if not payloads:
            return
        merged = ActionsPayload.merge(payloads)
        assert self._loop is not None
        task = self._loop.create_task(
            self._deliver(merged),
            name=f"agent-context-flush-{session_id}",
        )
        task.add_done_callback(
            lambda t: (
                logger.error(
                    "agent_context: debounce flush failed session=%s product=%s: %s",
                    session_id,
                    merged.product_id,
                    t.exception(),
                    exc_info=t.exception(),
                    extra={"session_id": session_id, "product_id": merged.product_id},
                )
                if not t.cancelled() and t.exception()
                else None
            )
        )

    async def _deliver(self, payload: ActionsPayload) -> None:
        """Forward a payload to ``write_actions`` and the summarizer.

        Called directly for non-debounced payloads, or from a flush task for
        debounced ones.

        Args:
            payload: The ``ActionsPayload`` to forward (may be a merged payload).
        """
        session_id = payload.session_id or "unknown"
        text = payload.to_text()

        if self._write_actions is not None:
            try:
                await self._write_actions(session_id, text)
            except Exception as exc:
                logger.error(
                    "agent_context: write_actions failed session=%s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                    extra={
                        "session_id": session_id,
                        "product_id": getattr(payload, "product_id", None),
                    },
                )

        await self._summarizer.add(payload)

    async def _on_summary(self, session_id: str, summary_text: str) -> None:
        """Receive the LLM summary from the summarizer and overwrite the destination.

        Called automatically by ``AsyncSessionSummarizer`` when the action
        threshold is reached and the LLM call has completed.

        ORDERING GUARANTEE: ``overwrite_with_summary`` is awaited to completion
        before this method returns.  Implement ``overwrite_with_summary`` so that
        the summary is posted to the destination first; only after that call
        returns should the old context be removed.  This prevents any window
        in which the agent has no context at all.

        Args:
            session_id:   The session whose actions have just been summarised.
            summary_text: The LLM-generated prose summary.
        """
        try:
            await self._overwrite_with_summary(session_id, summary_text)
            logger.debug(
                "agent_context: overwrote context with summary session=%s",
                session_id,
                extra={"session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "agent_context: overwrite_with_summary failed session=%s: %s",
                session_id,
                exc,
                exc_info=True,
                extra={"session_id": session_id},
            )
