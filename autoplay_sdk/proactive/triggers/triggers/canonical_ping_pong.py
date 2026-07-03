"""Ping-pong navigation between canonical URLs (hesitation / confusion).

Combines two complementary hesitation predicates so the trigger reflects
how users actually struggle in the product:

  - ``proactive_trigger_canonical_url_ping_pong`` (strict A→B→A) catches
    the classic two-page bounce: user opens settings, jumps to dashboard,
    realises they were right, bounces back. Tight, low false-positive,
    historically the only signal we had.

  - ``proactive_trigger_url_hesitation`` (≥N distinct + ≥1 repeat) catches
    the much more common "I tried three different pages looking for X and
    eventually went back". Strict ping-pong misses this entirely because
    no overlapping triple ever matches A=C.

The trigger fires on EITHER signal, with metadata recording which
heuristic matched so we can debug downstream tools (chip ranker, judge)
without rerunning the predicates.
"""

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


class CanonicalPingPongTrigger:
    """Wraps the hesitation predicates as a :class:`ProactiveTrigger`.

    Args:
        min_cycles:
            Strict A→B→A predicate threshold. Default 1.
        broaden_with_hesitation:
            When True (default) the trigger ALSO fires on the broader
            hesitation predicate (≥``hesitation_min_distinct`` distinct
            URLs with at least one revisit). Set False to recover the
            strict-only legacy behaviour.
        hesitation_min_distinct:
            Minimum distinct URLs required by the broader predicate.
            Default 3 — see docstring on
            :func:`proactive_trigger_url_hesitation`.
    """

    def __init__(
        self,
        *,
        min_cycles: int = 1,
        broaden_with_hesitation: bool = True,
        hesitation_min_distinct: int = 3,
    ) -> None:
        self._min_cycles = min_cycles
        self._broaden_with_hesitation = broaden_with_hesitation
        self._hesitation_min_distinct = hesitation_min_distinct

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_CANONICAL_URL_PING_PONG

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        urls = ctx.canonical_urls
        strict = proactive_trigger_canonical_url_ping_pong(
            urls, min_cycles=self._min_cycles
        )
        broad = self._broaden_with_hesitation and proactive_trigger_url_hesitation(
            urls, min_distinct=self._hesitation_min_distinct
        )
        if not strict and not broad:
            return None
        # Record which heuristic matched so downstream debugging can tell
        # apart "user bounced between two pages" vs "user searched 3
        # places then returned" — different mental models for the user,
        # potentially different chip ranking strategies later.
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
                "matched": matched,
                "hesitation_min_distinct": self._hesitation_min_distinct,
            },
        )
