"""Ordered registry of proactive triggers (first match wins for production UX)."""

from __future__ import annotations

from typing import Sequence

from autoplay_sdk.proactive_triggers.types import (
    ProactiveTrigger,
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)


class ProactiveTriggerRegistry:
    """Run triggers in registration order."""

    def __init__(self, triggers: Sequence[ProactiveTrigger]) -> None:
        self._triggers: tuple[ProactiveTrigger, ...] = tuple(triggers)

    @property
    def triggers(self) -> tuple[ProactiveTrigger, ...]:
        return self._triggers

    def evaluate_first(
        self, ctx: ProactiveTriggerContext
    ) -> ProactiveTriggerResult | None:
        """Return the first non-``None`` result (recommended for sending one proactive message)."""
        for t in self._triggers:
            out = t.evaluate(ctx)
            if out is not None:
                return out
        return None

    def evaluate_all(
        self, ctx: ProactiveTriggerContext
    ) -> list[ProactiveTriggerResult]:
        """Return every firing trigger (merge list for LLM judge + diagnostics)."""
        hits: list[ProactiveTriggerResult] = []
        for t in self._triggers:
            out = t.evaluate(ctx)
            if out is not None:
                hits.append(out)
        return hits
