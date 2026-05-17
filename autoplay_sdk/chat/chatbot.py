"""autoplay_sdk.chatbot — Base classes and protocol for building chatbot destinations.

This module provides the building blocks for connecting the Autoplay event connector
to any chatbot platform.  Customers who want to deliver session actions to a platform
other than Intercom (Zendesk, Salesforce, custom LLM agent, etc.) should:

1. Implement ``ConversationWriter`` — the typed protocol that the connector calls.
2. Subclass ``BaseChatbotWriter`` — to inherit pre-link buffering, post-link
   debouncing, and note formatting for free.

ConversationWriter protocol
---------------------------
The connector calls two methods on every writer:

    write_actions(conversation_id, session_id, slim_actions, ...)
        Deliver a batch of UI actions to the destination.  Called on every
        ``forward_batch`` cycle regardless of link state; implementations
        decide how to handle unlinked sessions.

    on_session_linked(session_id, conversation_id)
        Called once when a destination conversation_id is first associated
        with a PostHog session.  Use this to flush any pre-link buffer.

BaseChatbotWriter
-----------------
Concrete base class providing the full delivery policy:

    Pre-link (sliding window):
        Actions accumulate in memory.  Entries older than ``pre_link_window_s``
        seconds are dropped on every append.  No destination API call is made.

    At link time (on_session_linked):
        The entire buffer is flushed as a single ``_post_note`` call, with
        actions grouped into ``bin_seconds``-wide visual bins separated by
        blank lines.  One API call regardless of how many actions accumulated.

    Post-link (debounce):
        Each ``write_actions`` call appends to a per-session buffer and
        resets a ``post_link_debounce_s``-second ``asyncio.Task``.  When the
        timer fires, one ``_post_note`` call is made.  Rapid bursts are
        coalesced; a pause longer than the debounce window triggers delivery.

All three timing values are constructor parameters so they can be tuned
per-product via ``integration_config`` without a code deploy.

Ordering contract (with AsyncAgentContextWriter)
-------------------------------------------------
When used together with ``AsyncAgentContextWriter`` for LLM summarisation,
the delivery ordering must be:

    1. ``write_actions`` / ``_post_note`` — raw actions posted first.
    2. ``overwrite_with_summary`` — summary posted to destination.
    3. Redact / delete old raw-action notes only after step 2 confirms success.

This guarantees the agent destination never has a blank context window.
See ``autoplay_sdk.agent_context.AsyncAgentContextWriter`` for details.

AsyncAgentContextWriter.debounce_ms interaction
------------------------------------------------
``BaseChatbotWriter`` already coalesces rapid ``write_actions`` calls via its
own ``post_link_debounce_s`` window.  When wiring an ``AsyncAgentContextWriter``
to a ``BaseChatbotWriter`` subclass (via the ``write_actions`` callback), keep
``debounce_ms=0`` on the writer — the base class debounce is sufficient, and
stacking both windows only adds latency.

Use ``AsyncAgentContextWriter(debounce_ms=N)`` only when the ``write_actions``
callback calls a destination that has **no internal debouncing** (e.g. a raw
Zendesk or Salesforce API endpoint).

Note header helper
------------------
``format_chatbot_note_header(session_id, timestamp_unix)`` builds the standard
two-line header (``session_id:`` / ``timestamp:`` UTC) plus a blank line.
``BaseChatbotWriter`` uses it for action notes; call the same helper when
implementing ``overwrite_with_summary`` or any custom ``_post_note`` body so
all chatbot destinations stay consistent.

Quick-start (custom backend)::

    from autoplay_sdk.chatbot import BaseChatbotWriter

    class ZendeskChatbot(BaseChatbotWriter):
        def __init__(self, api_token, product_id, client,
                     pre_link_window_s=120.0, post_link_debounce_s=0.150, bin_seconds=3):
            super().__init__(product_id, pre_link_window_s, post_link_debounce_s, bin_seconds)
            self._api_token = api_token
            self._client = client

        async def _post_note(self, conversation_id: str, body: str) -> str | None:
            resp = await self._client.post(
                f"https://api.zendesk.com/tickets/{conversation_id}/comments",
                json={"comment": {"body": body, "public": False}},
                headers={"Authorization": f"Bearer {self._api_token}"},
            )
            return str(resp.json()["comment"]["id"])

        async def _redact_part(self, conversation_id: str, part_id: str) -> None:
            pass  # Zendesk comments are immutable; no-op
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


def format_chatbot_note_header(session_id: str | None, timestamp_unix: float) -> str:
    """Build the standard chatbot note header (two lines + blank line).

    Use for action timelines, LLM summaries, or any other note posted to a
    chatbot backend so formatting matches across integrations.

    Args:
        session_id: PostHog session id; displayed as ``unknown`` when falsy.
        timestamp_unix: POSIX seconds (e.g. from an action's ``timestamp_start``
            or ``time.time()`` at post time), rendered as UTC.

    Returns:
        String ending with ``\\n\\n`` ready to prepend before the note body.
    """
    sid = session_id or "unknown"
    ts = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    return f"session_id: {sid}\ntimestamp: {ts}\n\n"


# ---------------------------------------------------------------------------
# Session-link webhook DTO (shared by connector + BaseChatbotWriter)
# ---------------------------------------------------------------------------


@dataclass
class ConversationEvent:
    """Normalised session-link payload extracted from a chatbot platform webhook.

    The connector uses this to look up the PostHog ``session_id`` and link it
    to the platform ``conversation_id``.

    Attributes:
        conversation_id: Platform-specific conversation identifier.
        external_id: User's external ID in the platform (maps to PostHog
            ``distinct_id`` via the identity store).
        email: User's email; fallback lookup when ``external_id`` is absent
            or yields no match.
    """

    conversation_id: str
    external_id: str = field(default="")
    email: str = field(default="")


# ---------------------------------------------------------------------------
# ConversationWriter — formal typed protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationWriter(Protocol):
    """Typed protocol for all writer destinations used by the Autoplay connector.

    The connector's ``forward_batch`` function calls these two methods on every
    writer instance.  Any class implementing both is a valid ``ConversationWriter``:
    ``IntercomChatbot``, ``SseWriter``, ``WebhookWriter``, and any custom backend.

    Implementations that need pre/post-link routing should subclass
    ``BaseChatbotWriter`` rather than implementing this protocol from scratch.
    """

    async def write_actions(
        self,
        conversation_id: str,
        session_id: str | None,
        slim_actions: list[dict],
        user_id: str | None = None,
        email: str | None = None,
    ) -> str | None:
        """Deliver a batch of UI actions to the destination.

        Called on every ``forward_batch`` cycle.  Pre-link implementations
        should buffer actions (no destination call yet); post-link
        implementations should deliver immediately or via a debounce window.

        Args:
            conversation_id: Platform-specific conversation id (may be empty
                             pre-link for chatbot destinations).
            session_id:      PostHog session identifier.
            slim_actions:    Ordered list of ``{index, description,
                             timestamp_start, …}`` dicts.
            user_id:         Identified user id (optional).
            email:           User email (optional).

        Returns:
            Platform-specific part/note id on success, or None.
        """
        ...

    async def on_session_linked(
        self,
        session_id: str,
        conversation_id: str,
    ) -> None:
        """Notify the writer that a destination conversation has been linked.

        Called once when a destination ``conversation_id`` is first associated
        with a PostHog session.  Writers that buffer pre-link actions should
        flush them here.  No-op for destinations that do not use the link
        concept (e.g. SSE, webhook).

        Args:
            session_id:      PostHog session identifier.
            conversation_id: Platform-specific conversation id now linked.
        """
        ...


# ---------------------------------------------------------------------------
# BaseChatbotWriter — shared delivery policy for all chatbot destinations
# ---------------------------------------------------------------------------


class BaseChatbotWriter:
    """Shared pre-link/post-link delivery logic for all chatbot destinations.

    Subclasses must implement ``_post_note`` and ``_redact_part``.

    Session-link webhooks (optional, per platform):
        Set :attr:`SESSION_LINK_WEBHOOK_TOPICS` to the vendor topic strings that
        may trigger linking (typically "new conversation" + "user replied").
        Override :meth:`_parse_session_link_webhook_payload` to map JSON to
        :class:`ConversationEvent`. Do not override :meth:`extract_conversation_event`.

    Delivery modes:

    Pre-link (sliding window):
        ``write_actions`` appends to ``_pending[session_id]`` and trims
        entries older than ``pre_link_window_s`` seconds.  No API call.

    At link time (``on_session_linked``):
        The full ``_pending`` buffer is flushed as a single ``_post_note``
        call.  Actions are grouped into ``bin_seconds``-wide bins separated
        by blank lines — one API call regardless of how many actions.

    Post-link (debounce):
        ``write_actions`` extends ``_debounce_buffer[session_id]`` and
        cancels/restarts a ``post_link_debounce_s``-second ``asyncio.Task``.
        When the timer fires, one ``_post_note`` call is made.

    Args:
        product_id:           Product identifier for metrics/logging.
        pre_link_window_s:    Seconds of actions to retain in the pre-link
                              sliding window. Default 120 (2 minutes).
        post_link_debounce_s: Seconds to wait after the last action before
                              posting a note post-link. Default 0.15 (150 ms).
        bin_seconds:          Width of time bins (in seconds) used to insert
                              blank-line separators in the flush note.
                              Default 3. Set to 0 to disable binning.
    """

    #: Inbound webhook ``topic`` values that may trigger session→conversation linking.
    #: Empty tuple means this integration does not use the generic chatbot webhook path.
    SESSION_LINK_WEBHOOK_TOPICS: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        product_id: str,
        pre_link_window_s: float = 120.0,
        post_link_debounce_s: float = 0.150,
        bin_seconds: int = 3,
    ) -> None:
        self._product_id = product_id
        self._pre_link_window_s = pre_link_window_s
        self._post_link_debounce_s = post_link_debounce_s
        self._bin_seconds = bin_seconds
        # session_id → platform conversation_id; populated by on_session_linked()
        self._conv_map: dict[str, str] = {}
        # session_id → list of platform part/note ids for redaction
        self._part_ids: dict[str, list[str]] = defaultdict(list)
        # pre-link: accumulates slim_actions until on_session_linked fires
        self._pending: dict[str, list[dict]] = defaultdict(list)
        # post-link: short-lived buffer drained by the debounce task
        self._debounce_buffer: dict[str, list[dict]] = defaultdict(list)
        # post-link: one asyncio.Task per session; cancelled/restarted on each write
        self._debounce_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Chatbot webhook protocol (class methods — connector dispatches here)
    # ------------------------------------------------------------------

    @classmethod
    def extract_conversation_event(cls, payload: dict) -> ConversationEvent | None:
        """Return a :class:`ConversationEvent` when ``topic`` is link-eligible.

        Subclasses should not override this method; implement
        :meth:`_parse_session_link_webhook_payload` instead.
        """
        topic = str(payload.get("topic", ""))
        if (
            not cls.SESSION_LINK_WEBHOOK_TOPICS
            or topic not in cls.SESSION_LINK_WEBHOOK_TOPICS
        ):
            return None
        return cls._parse_session_link_webhook_payload(payload)

    @classmethod
    def _parse_session_link_webhook_payload(
        cls, payload: dict
    ) -> ConversationEvent | None:
        """Map vendor webhook JSON to :class:`ConversationEvent`.

        Default returns ``None``. Platform integrations override when
        :attr:`SESSION_LINK_WEBHOOK_TOPICS` is non-empty.
        """
        return None

    # ------------------------------------------------------------------
    # Subclass contract — platform API primitives
    # ------------------------------------------------------------------

    async def _post_note(self, conversation_id: str, body: str) -> str | None:
        """Post a note to the platform conversation. Return its id or None."""
        raise NotImplementedError

    async def _redact_part(self, conversation_id: str, part_id: str) -> None:
        """Delete or blank a previously posted note (best-effort)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # ConversationWriter protocol — routing logic
    # ------------------------------------------------------------------

    async def on_session_linked(self, session_id: str, conversation_id: str) -> None:
        """Store the session→conversation mapping and flush the pre-link buffer.

        No-ops if the session is already linked (idempotent).  This prevents
        two problems that arise when the worker calls this on every batch for
        already-linked sessions:
          1. Unnecessary cancellation of an in-flight post-link debounce task,
             which would endlessly reset the 150ms window during fast bursts.
          2. Spurious ``_pending.pop()`` (always returns []) causing a redundant
             loop iteration.

        On first link, flushes any buffered pre-link actions as a single note
        grouped into ``bin_seconds``-wide visual bins.  The ``_pending`` buffer
        is cleared only after ``_post_note`` confirms success — if the API call
        fails the buffer is preserved so the actions can be retried on the next
        ``on_session_linked`` call (e.g. after a process restart or re-link).

        Args:
            session_id:      PostHog session identifier.
            conversation_id: Platform-specific conversation id.
        """
        if self._conv_map.get(session_id) == conversation_id:
            # Same conv_id seen again — already fully processed, nothing to do.
            # This is the common case: the product worker includes the conv_id
            # in every batch for already-linked sessions, so this guard prevents
            # unnecessary debounce cancellations and no-op buffer pops.
            return

        self._conv_map[session_id] = conversation_id

        pending = self._pending.get(session_id, [])
        if pending:
            logger.debug(
                "base_writer: flushing %d pre-link actions for session=%s conv=%s",
                len(pending),
                session_id,
                conversation_id,
            )
            part_id = await self._post_note(
                conversation_id,
                self._format_note(session_id, pending),
            )
            if part_id:
                # Delivery confirmed — clear the buffer and record the part id.
                self._pending.pop(session_id, None)
                self._part_ids[session_id].append(part_id)
            else:
                # API call failed — leave _pending intact so the next
                # on_session_linked call (after a retry or re-link) can try again.
                logger.warning(
                    "base_writer: pre-link flush failed for session=%s conv=%s"
                    " — buffer preserved for retry",
                    session_id,
                    conversation_id,
                    extra={
                        "session_id": session_id,
                        "product_id": self._product_id,
                        "conversation_id": conversation_id,
                    },
                )
                # Undo the conv_map entry so this session is treated as
                # unlinked on the next attempt.
                del self._conv_map[session_id]
                return
        else:
            self._pending.pop(session_id, None)

        task = self._debounce_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    async def write_actions(
        self,
        conversation_id: str,
        session_id: str | None,
        slim_actions: list[dict],
        user_id: str | None = None,
        email: str | None = None,
    ) -> str | None:
        """Route slim_actions to the appropriate delivery path.

        Pre-link: appends to the sliding-window buffer, no API call.
        Post-link: feeds the debounce pipeline.

        Args:
            conversation_id: Passed through but ignored — resolved from
                             internal session map for chatbot destinations.
            session_id:      PostHog session identifier.
            slim_actions:    Ordered list of ``{index, description,
                             timestamp_start, …}`` dicts.
            user_id:         Ignored (available for subclass use if needed).
            email:           Ignored (available for subclass use if needed).

        Returns:
            None always — actual delivery is async via the debounce task.
        """
        if not slim_actions:
            return None

        real_conv_id = self._conv_map.get(session_id or "")
        sid = session_id or ""

        if not real_conv_id:
            # Pre-link: buffer and enforce the sliding window
            buf = self._pending[sid]
            buf.extend(slim_actions)
            cutoff = time.time() - self._pre_link_window_s
            self._pending[sid] = [
                a for a in buf if (a.get("timestamp_start") or 0) >= cutoff
            ]
            logger.debug(
                "base_writer: buffered %d actions pre-link for session=%s (%d total)",
                len(slim_actions),
                sid,
                len(self._pending[sid]),
            )
            return None

        # Post-link: debounce
        self._debounce_buffer[sid].extend(slim_actions)
        existing = self._debounce_tasks.get(sid)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._debounce_flush(sid, real_conv_id))
        task.add_done_callback(
            lambda t, s=sid: (
                logger.error(
                    "base_writer: debounce flush failed session=%s product=%s: %s",
                    s,
                    self._product_id,
                    t.exception(),
                    exc_info=t.exception(),
                    extra={"session_id": s, "product_id": self._product_id},
                )
                if not t.cancelled() and t.exception()
                else None
            )
        )
        self._debounce_tasks[sid] = task
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _debounce_flush(self, session_id: str, conversation_id: str) -> None:
        """Wait for the debounce window, then post all buffered post-link actions.

        Cancelled and restarted on every new ``write_actions`` call for this
        session, so the timer always measures silence since the last action.
        """
        try:
            await asyncio.sleep(self._post_link_debounce_s)
        except asyncio.CancelledError:
            return

        actions = self._debounce_buffer.pop(session_id, [])
        if not actions:
            return

        part_id = await self._post_note(
            conversation_id,
            self._format_note(session_id, actions, bin_seconds=0),
        )
        if part_id:
            self._part_ids[session_id].append(part_id)
        else:
            logger.warning(
                "base_writer: post-link debounce flush failed for session=%s conv=%s"
                " — _post_note returned no part_id; debounce buffer already popped"
                " (this flush is not retried automatically)",
                session_id,
                conversation_id,
                extra={
                    "session_id": session_id,
                    "product_id": self._product_id,
                    "conversation_id": conversation_id,
                },
            )

    def _format_note(
        self,
        session_id: str | None,
        slim_actions: list[dict],
        bin_seconds: int | None = None,
    ) -> str:
        """Format slim_actions into a plain-text note body.

        The full contract (header lines, sorting, 1-based ``[n]`` ordinals,
        binning vs post-link, empty list) is documented under **Note body format**
        on the BaseChatbotWriter docs page (``sdk/chatbot-writer``).

        Args:
            session_id:   PostHog session id used in the note header.
            slim_actions: Action dicts with ``description`` and ``timestamp_start``.
            bin_seconds:  Override ``_bin_seconds`` for this call.
                          Pass ``0`` to disable binning (used for post-link notes).
                          Defaults to ``self._bin_seconds``.

        Returns:
            Plain-text note body string.
        """
        effective_bins = self._bin_seconds if bin_seconds is None else bin_seconds

        if not slim_actions:
            return format_chatbot_note_header(session_id, time.time())

        sorted_actions = sorted(
            slim_actions,
            key=lambda a: float(a.get("timestamp_start") or 0.0),
        )
        first_ts_raw = sorted_actions[0].get("timestamp_start")
        header_ts = float(first_ts_raw) if first_ts_raw is not None else time.time()
        header = format_chatbot_note_header(session_id, header_ts)

        action_lines: list[str] = []
        prev_bin: int | None = None
        for i, a in enumerate(sorted_actions, start=1):
            if effective_bins:
                cur_bin = int((a.get("timestamp_start") or 0) // effective_bins)
                if prev_bin is not None and cur_bin != prev_bin:
                    action_lines.append("")
                prev_bin = cur_bin
            action_lines.append(f"[{i}] {a.get('description', '')}")

        return header + "\n".join(action_lines)
