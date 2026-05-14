"""Ping-pong navigation between canonical URLs (hesitation / confusion)."""

from __future__ import annotations

from autoplay_sdk.integrations.intercom import proactive_trigger_canonical_url_ping_pong
from autoplay_sdk.proactive_triggers.defaults import (
    DEFAULT_PROACTIVE_QUICK_REPLY_BODY,
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
)
from autoplay_sdk.proactive_triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)


class CanonicalPingPongTrigger:
    """Wraps :func:`proactive_trigger_canonical_url_ping_pong` as a :class:`ProactiveTrigger`."""

    def __init__(self, *, min_cycles: int = 1) -> None:
        self._min_cycles = min_cycles

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_CANONICAL_URL_PING_PONG

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        if not proactive_trigger_canonical_url_ping_pong(
            ctx.canonical_urls,
            min_cycles=self._min_cycles,
        ):
            return None
        return ProactiveTriggerResult(
            trigger_id=self.trigger_id,
            body=DEFAULT_PROACTIVE_QUICK_REPLY_BODY,
            metadata={"min_cycles": self._min_cycles},
        )
