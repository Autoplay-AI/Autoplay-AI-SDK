"""Ping-pong trigger scoped to canonical URLs that touch a required substring."""

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
from autoplay_sdk.proactive_triggers.url_scope import canonical_urls_touch_substring


class ScopedCanonicalPingPongTrigger:
    """Canonical URL ping-pong where recent URLs must also touch ``url_must_contain``.

    Composes the same oscillation check as :class:`CanonicalPingPongTrigger` with an
    additional URL gate for hosts that need path/prefix scoping (e.g. ``/projects``).
    """

    def __init__(
        self,
        *,
        url_must_contain: str,
        min_cycles: int = 1,
    ) -> None:
        self._url_must_contain = (url_must_contain or "").strip()
        self._min_cycles = min_cycles

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_CANONICAL_URL_PING_PONG

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        if self._url_must_contain and not canonical_urls_touch_substring(
            ctx.canonical_urls, self._url_must_contain
        ):
            return None
        if not proactive_trigger_canonical_url_ping_pong(
            ctx.canonical_urls,
            min_cycles=self._min_cycles,
        ):
            return None
        return ProactiveTriggerResult(
            trigger_id=self.trigger_id,
            body=DEFAULT_PROACTIVE_QUICK_REPLY_BODY,
            metadata={
                "min_cycles": self._min_cycles,
                "scoped_canonical_url_contains": self._url_must_contain,
            },
        )
