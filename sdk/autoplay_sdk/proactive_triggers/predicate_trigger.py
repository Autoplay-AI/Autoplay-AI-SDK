"""Boolean-predicate trigger — minimal boilerplate for custom :class:`ProactiveTrigger` logic."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from autoplay_sdk.proactive_triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)


class PredicateProactiveTrigger:
    """Fire when ``predicate(ctx)`` is true; build a fixed :class:`ProactiveTriggerResult`.

    Pass a function that reads :class:`ProactiveTriggerContext` (URLs, ``recent_actions``,
    summaries, ``context_extra``, etc.). Use either **metadata** (static) **or**
    **metadata_fn** (per-context); if both are set, **metadata_fn** wins.

    Args:
        trigger_id: Stable id for analytics and cooldown keys.
        body: Offer copy when the trigger fires.
        predicate: ``(ctx) -> bool`` — ``True`` means emit a result.
        reply_option_labels: Optional quick-reply labels for channels that support them.
        metadata: Static metadata merged into :attr:`ProactiveTriggerResult.metadata`.
        metadata_fn: If set, called with ``ctx`` to build result metadata (overrides ``metadata``).
    """

    def __init__(
        self,
        *,
        trigger_id: str,
        body: str,
        predicate: Callable[[ProactiveTriggerContext], bool],
        reply_option_labels: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        metadata_fn: Callable[[ProactiveTriggerContext], dict[str, Any]] | None = None,
    ) -> None:
        self._trigger_id = trigger_id
        self._body = body
        self._predicate = predicate
        self._reply_option_labels = tuple(reply_option_labels)
        self._metadata = dict(metadata) if metadata is not None else None
        self._metadata_fn = metadata_fn

    @property
    def trigger_id(self) -> str:
        return self._trigger_id

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        if not self._predicate(ctx):
            return None
        if self._metadata_fn is not None:
            meta = dict(self._metadata_fn(ctx))
        elif self._metadata is not None:
            meta = dict(self._metadata)
        else:
            meta = {}
        return ProactiveTriggerResult(
            trigger_id=self._trigger_id,
            body=self._body,
            reply_option_labels=self._reply_option_labels,
            metadata=meta,
        )
