"""Wrap a :class:`ProactiveTrigger` with plug-and-play timing policy."""

from __future__ import annotations

from dataclasses import replace

from autoplay_sdk.proactive_triggers.judge import META_TRIGGERING_TYPE
from autoplay_sdk.proactive_triggers.types import (
    ProactiveTrigger,
    ProactiveTriggerContext,
    ProactiveTriggerResult,
    ProactiveTriggerTimings,
)


class ProactiveTriggerEntity:
    """Attach :class:`ProactiveTriggerTimings` to any trigger.

    On fire, merges timings onto the inner :class:`ProactiveTriggerResult` via
    :func:`dataclasses.replace` so callers read ``interaction_timeout_s`` and
    ``cooldown_s`` from the result without a separate lookup.

    **triggering_type** — when set, merges :data:`META_TRIGGERING_TYPE` into result
    metadata for partition / LLM judge routing.
    """

    def __init__(
        self,
        inner: ProactiveTrigger,
        timings: ProactiveTriggerTimings | None = None,
        *,
        triggering_type: str | None = None,
    ) -> None:
        self._inner = inner
        self._timings = timings if timings is not None else ProactiveTriggerTimings()
        self._triggering_type = triggering_type

    @property
    def trigger_id(self) -> str:
        return self._inner.trigger_id

    @property
    def timings(self) -> ProactiveTriggerTimings:
        return self._timings

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        out = self._inner.evaluate(ctx)
        if out is None:
            return None
        md = dict(out.metadata)
        if self._triggering_type is not None:
            md.setdefault(META_TRIGGERING_TYPE, self._triggering_type)
        return replace(
            out,
            interaction_timeout_s=self._timings.interaction_timeout_s,
            cooldown_s=self._timings.cooldown_s,
            metadata=md,
        )
