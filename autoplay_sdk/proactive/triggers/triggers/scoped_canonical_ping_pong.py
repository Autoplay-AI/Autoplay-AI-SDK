"""Ping-pong trigger scoped to canonical URLs that touch a required substring."""

from __future__ import annotations

from autoplay_sdk.proactive.triggers._url_predicates import (
    proactive_trigger_canonical_url_ping_pong,
    proactive_trigger_url_hesitation,
)
from autoplay_sdk.proactive.triggers.defaults import (
    DEFAULT_PROACTIVE_QUICK_REPLY_BODY,
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
)
from autoplay_sdk.proactive.triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)
from autoplay_sdk.proactive.triggers.url_scope import canonical_urls_touch_substring


class ScopedCanonicalPingPongTrigger:
    """Canonical URL ping-pong (or broader hesitation) within a URL substring scope.

    Composes the same hesitation checks as :class:`CanonicalPingPongTrigger`
    with an additional URL substring gate for hosts that need path/prefix
    scoping (e.g. ``/projects``). Fires when EITHER the strict A→B→A
    predicate OR the broader hesitation predicate (≥N distinct + ≥1
    revisit) matches the in-scope URL sequence — mirroring the unscoped
    sibling, so the two triggers agree on what "user is struggling" means
    and only differ on where it counts.
    """

    def __init__(
        self,
        *,
        url_must_contain: str,
        min_cycles: int = 1,
        broaden_with_hesitation: bool = True,
        hesitation_min_distinct: int = 3,
    ) -> None:
        self._url_must_contain = (url_must_contain or "").strip()
        self._min_cycles = min_cycles
        self._broaden_with_hesitation = broaden_with_hesitation
        self._hesitation_min_distinct = hesitation_min_distinct

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_CANONICAL_URL_PING_PONG

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        if self._url_must_contain and not canonical_urls_touch_substring(
            ctx.canonical_urls, self._url_must_contain
        ):
            return None
        urls = ctx.canonical_urls
        strict = proactive_trigger_canonical_url_ping_pong(
            urls, min_cycles=self._min_cycles
        )
        # The strict A→B→A predicate already needs all three of A, B, A to
        # be in scope to match, so it is self-scoping. The broader
        # hesitation predicate doesn't know about scope on its own — if
        # we pass it the raw URL stream it can fire from out-of-scope
        # navigation (e.g. user hesitated in /settings) as soon as the
        # ``url_must_contain`` gate above let one in-scope URL through.
        # Filter to in-scope URLs first so this trigger only counts
        # hesitation that actually happened in our scope.
        scoped_urls = (
            [u for u in urls if u and self._url_must_contain in u]
            if self._url_must_contain
            else list(urls)
        )
        broad = self._broaden_with_hesitation and proactive_trigger_url_hesitation(
            scoped_urls, min_distinct=self._hesitation_min_distinct
        )
        if not strict and not broad:
            return None
        matched: list[str] = []
        if strict:
            matched.append("strict_ping_pong")
        if broad:
            matched.append("hesitation_distinct_with_revisit")
        return ProactiveTriggerResult(
            trigger_id=self.trigger_id,
            body=DEFAULT_PROACTIVE_QUICK_REPLY_BODY,
            metadata={
                "min_cycles": self._min_cycles,
                "scoped_canonical_url_contains": self._url_must_contain,
                "matched": matched,
                "hesitation_min_distinct": self._hesitation_min_distinct,
            },
        )
