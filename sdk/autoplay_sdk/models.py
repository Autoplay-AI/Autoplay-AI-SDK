"""autoplay_sdk.models — Typed payload models for Autoplay SSE events.

These dataclasses mirror the JSON payloads emitted by the Autoplay event
connector pipeline.  All public fields match the wire format exactly so
``ActionsPayload.from_dict(raw)`` and ``SummaryPayload.from_dict(raw)``
are lossless round-trips.

Each model exposes a ``to_text()`` method that returns an embedding-ready
plain-text representation of the payload — suitable for direct use as the
``input`` to any embedding API (OpenAI, Cohere, Hugging Face, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SlimAction:
    """A single UI action extracted from a user session.

    Attributes:
        index:           0-based position of this action in the session sequence.
        type:            Event type in lowercase (e.g. ``"pageview"``, ``"click"``,
                         ``"submit"``).
        title:           Human-readable label for the page or element
                         (e.g. ``"Page Load: Dashboard"`` or ``"Export CSV button"``).
        description:     Natural-language description of what the user did
                         (e.g. ``"User landed on the main Dashboard page"``).
        timestamp_start: Unix timestamp (float) when the action began.
        timestamp_end:   Unix timestamp (float) when the action ended.  For the
                         last action in a batch this equals ``timestamp_start``.
        raw_url:         Original URL as captured, before canonicalization.
        canonical_url:   Normalised URL with dynamic path segments collapsed to
                         ``:id`` (e.g. ``"https://app.example.com/projects/:id"``).
        session_id:      PostHog session id for this action; ``None`` if unknown.
        user_id:         Distinct id / identified user id; ``None`` if anonymous.
        email:           User email from PostHog properties when present; ``None``
                         if absent.
        conversation_id: Intercom (or channel) conversation id when the PostHog
                         session is linked; ``None`` until linking (see connector
                         session store). Optional on the wire.
    """

    title: str
    description: str
    canonical_url: str
    index: int = 0
    type: str = ""
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    raw_url: str = ""
    session_id: str | None = None
    user_id: str | None = None
    email: str | None = None
    conversation_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlimAction":
        """Construct a ``SlimAction`` from a raw pipeline dict.

        Args:
            data: Mapping with any subset of SlimAction field names.  Missing
                  or falsy values fall back to the field defaults (``""`` /
                  ``0`` / ``0.0``). Identity fields default to ``None`` when omitted.

        Returns:
            A fully populated ``SlimAction`` instance.
        """
        return cls(
            title=data.get("title") or "",
            description=data.get("description") or "",
            canonical_url=data.get("canonical_url") or "",
            index=data.get("index") or 0,
            type=data.get("type") or "",
            timestamp_start=data.get("timestamp_start") or 0.0,
            timestamp_end=data.get("timestamp_end") or 0.0,
            raw_url=data.get("raw_url") or "",
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            email=data.get("email"),
            conversation_id=data.get("conversation_id"),
        )

    def to_text(self) -> str:
        """Return a one-line text representation for embedding or logging.

        Format: ``[{index}] {type}: {description} — {canonical_url}``

        Example::

            [0] pageview: User landed on the main Dashboard page — https://app.example.com/dashboard
            [1] click: User clicked Export CSV button — https://app.example.com/dashboard
        """
        return f"[{self.index}] {self.type}: {self.description} — {self.canonical_url}"


@dataclass
class ActionsPayload:
    """A batch of UI actions for a single session, as emitted by the pipeline.

    Delivered via the SSE stream when the connector has extracted and
    forwarded a batch of user interactions.

    Attributes:
        product_id:   Connector product identifier.
        session_id:   User session identifier (may be ``None`` for
                      anonymous sessions before identity linking).
        user_id:      External user identifier passed at Intercom boot
                      (typically the connector's ``distinct_id``).  ``None``
                      when the session is fully anonymous.
        email:        User e-mail if available from the identity store.
        actions:      Ordered list of UI actions in this batch.
        count:        Number of actions in this batch (equals
                      ``len(actions)``).
        forwarded_at: Unix timestamp (float) when the connector forwarded
                      this batch.
        conversation_id: Set when the session is linked to a chat thread; ``None``
                         before link.
    """

    product_id: str
    session_id: str | None
    user_id: str | None
    email: str | None
    actions: list[SlimAction]
    count: int
    forwarded_at: float
    conversation_id: str | None = None

    def __post_init__(self) -> None:
        """Warn when ``count`` disagrees with ``len(actions)``."""
        if self.count != len(self.actions):
            logger.warning(
                "autoplay_sdk: ActionsPayload.count=%d does not match len(actions)=%d "
                "for session=%s — using len(actions) as the authoritative value",
                self.count,
                len(self.actions),
                self.session_id,
            )
            self.count = len(self.actions)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionsPayload":
        """Construct an ``ActionsPayload`` from a raw SSE payload dict.

        Args:
            data: Parsed JSON payload from the SSE stream or Redis buffer.
                  The ``"actions"`` key should be a list of dicts; each is
                  passed to ``SlimAction.from_dict``.  Missing or falsy fields
                  fall back to safe defaults.

        Returns:
            A fully populated ``ActionsPayload`` instance.  ``__post_init__``
            reconciles ``count`` against ``len(actions)`` if they disagree.
        """
        raw_actions = data.get("actions") or []
        return cls(
            product_id=data.get("product_id") or "",
            session_id=data.get("session_id") or None,
            user_id=data.get("user_id") or None,
            email=data.get("email") or None,
            actions=[SlimAction.from_dict(a) for a in raw_actions],
            count=data.get("count") or 0,
            forwarded_at=data.get("forwarded_at") or 0.0,
            conversation_id=data.get("conversation_id"),
        )

    @classmethod
    def merge(cls, payloads: list["ActionsPayload"]) -> "ActionsPayload":
        """Merge multiple ``ActionsPayload`` objects for the same session into one.

        Concatenates action lists, re-indexes actions sequentially from 0,
        resolves identity fields from the first non-``None`` value across all
        payloads, and sets ``forwarded_at`` to the latest timestamp.

        This is used by ``AsyncAgentContextWriter`` when ``debounce_ms > 0`` to
        batch several rapid-fire payloads into a single destination API call.

        Args:
            payloads: Non-empty list of ``ActionsPayload`` objects, all for the
                      same session.  The first element provides ``product_id``
                      and ``session_id``.

        Returns:
            A single merged ``ActionsPayload``.

        Raises:
            ValueError: if ``payloads`` is empty.

        Example::

            merged = ActionsPayload.merge([payload_a, payload_b, payload_c])
            # merged.actions == [*a.actions, *b.actions, *c.actions] (re-indexed)
            # merged.forwarded_at == max(a.forwarded_at, b.forwarded_at, c.forwarded_at)
        """
        if not payloads:
            raise ValueError("ActionsPayload.merge() requires at least one payload")
        first = payloads[0]
        all_actions: list[SlimAction] = []
        for p in payloads:
            for action in p.actions:
                all_actions.append(replace(action, index=len(all_actions)))
        user_id = next((p.user_id for p in payloads if p.user_id), None)
        email = next((p.email for p in payloads if p.email), None)
        conversation_id = next(
            (p.conversation_id for p in payloads if p.conversation_id), None
        )
        return cls(
            product_id=first.product_id,
            session_id=first.session_id,
            user_id=user_id,
            email=email,
            actions=all_actions,
            count=len(all_actions),
            forwarded_at=max(p.forwarded_at for p in payloads),
            conversation_id=conversation_id,
        )

    def to_text(self) -> str:
        """Return an embedding-ready plain-text representation of this batch.

        Format::

            Session <session_id> — <N> actions
            [0] <type>: <description> — <canonical_url>
            [1] <type>: <description> — <canonical_url>
            ...

        The ``session_id`` line uses ``"unknown"`` when the session has not
        yet been linked to an identity.

        Example::

            Session ps_abc123 — 3 actions
            [0] pageview: User landed on the main Dashboard page — https://app.example.com/dashboard
            [1] click: User clicked Export CSV button — https://app.example.com/dashboard
            [2] click: User opened billing settings — https://app.example.com/settings/billing
        """
        sid = self.session_id or "unknown"
        lines = [f"Session {sid} — {len(self.actions)} actions"]
        for action in self.actions:
            lines.append(action.to_text())
        return "\n".join(lines)


@dataclass
class SummaryPayload:
    """An LLM-generated prose summary of a user session.

    Delivered via the SSE stream when the connector's summariser has
    condensed a session's action history into a compact paragraph.  This
    replaces the raw action list for context-window efficiency in RAG
    pipelines.

    Attributes:
        product_id:   Connector product identifier.
        session_id:   User session identifier.
        summary:      Prose description of what the user did during the
                      session up to this point.
        replaces:     Number of individual actions this summary replaces.
        forwarded_at: Unix timestamp (float) when the connector forwarded
                      this summary.
    """

    product_id: str
    session_id: str | None
    summary: str
    replaces: int
    forwarded_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SummaryPayload":
        """Construct a ``SummaryPayload`` from a raw SSE payload dict.

        Args:
            data: Parsed JSON payload from the SSE stream or Redis buffer.
                  Missing or falsy fields fall back to safe defaults.

        Returns:
            A fully populated ``SummaryPayload`` instance.
        """
        return cls(
            product_id=data.get("product_id") or "",
            session_id=data.get("session_id") or None,
            summary=data.get("summary") or "",
            replaces=data.get("replaces") or 0,
            forwarded_at=data.get("forwarded_at") or 0.0,
        )

    def to_text(self) -> str:
        """Return the prose summary, ready for embedding or LLM context.

        This is simply the ``summary`` string itself — no transformation
        needed.  The method exists for API symmetry with ``ActionsPayload``
        so callers can call ``.to_text()`` on any payload type without
        branching.

        Example::

            The user navigated to the Dashboard, exported a CSV report,
            then opened account settings to update their billing plan.
        """
        return self.summary


# Type alias exported for use in callback type hints.
AnyPayload = ActionsPayload | SummaryPayload

__all__ = [
    "SlimAction",
    "ActionsPayload",
    "SummaryPayload",
    "AnyPayload",
]
