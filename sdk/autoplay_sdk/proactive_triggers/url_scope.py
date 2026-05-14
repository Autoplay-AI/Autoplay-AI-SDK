"""Canonical URL substring checks for scoped proactive triggers (e.g. Projects pages)."""

from __future__ import annotations

from typing import Sequence

from autoplay_sdk.proactive_triggers.defaults import TRIGGER_ID_CANONICAL_URL_PING_PONG
from autoplay_sdk.proactive_triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)


def canonical_urls_touch_substring(
    canonical_urls: Sequence[str | None], substring: str
) -> bool:
    """True when any non-empty canonical URL contains ``substring`` (case-sensitive).

    Used to scope ping-pong and similar triggers to part of the product (e.g. a path
    prefix on ``https://app.example/...``). Normalization: empty or all-None → False
    if ``substring`` is non-empty.
    """
    sub = (substring or "").strip()
    if not sub:
        return True
    for u in canonical_urls:
        s = (u or "").strip()
        if s and sub in s:
            return True
    return False


def filter_ping_pong_hits_by_canonical_url_contains(
    ctx: ProactiveTriggerContext,
    hits: list[ProactiveTriggerResult],
    substring: str,
) -> list[ProactiveTriggerResult]:
    """Drop canonical URL ping-pong hits when recent URLs do not touch ``substring``.

    When ``substring`` is empty, returns ``hits`` unchanged. Non–ping-pong hits are
    always kept.
    """
    sub = (substring or "").strip()
    if not sub:
        return hits
    out: list[ProactiveTriggerResult] = []
    for h in hits:
        if h.trigger_id != TRIGGER_ID_CANONICAL_URL_PING_PONG:
            out.append(h)
            continue
        if canonical_urls_touch_substring(ctx.canonical_urls, sub):
            out.append(h)
    return out
