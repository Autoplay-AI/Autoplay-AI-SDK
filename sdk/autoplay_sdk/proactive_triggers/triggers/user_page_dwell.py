"""User page dwell — same canonical URL for ≥ threshold with sparse actions only.

Defaults (override via ``context_extra`` / ``integration_config.proactive_triggers``):

- ``dwell_threshold_seconds``: **60** — minimum dwell time in seconds (`DEFAULT_USER_PAGE_DWELL_THRESHOLD_S`).
- ``user_page_dwell_max_actions``: **5** — max actions on the trailing URL streak (`DEFAULT_USER_PAGE_DWELL_MAX_ACTIONS`).

See ``docs/sdk/proactive-triggers.mdx`` in the customer SDK docs package.
"""

from __future__ import annotations

import time
from typing import Any

from autoplay_sdk.models import SlimAction
from autoplay_sdk.proactive_triggers.defaults import TRIGGER_ID_USER_PAGE_DWELL
from autoplay_sdk.proactive_triggers.judge import validate_or_truncate_proactive_body
from autoplay_sdk.proactive_triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)

DEFAULT_USER_PAGE_DWELL_THRESHOLD_S = 60.0
DEFAULT_USER_PAGE_DWELL_MAX_ACTIONS = 5


def _trailing_run_same_url(actions: tuple[SlimAction, ...]) -> tuple[SlimAction, ...]:
    """Longest suffix of **actions** where ``canonical_url`` matches the last row."""
    if not actions:
        return ()
    last_url = (actions[-1].canonical_url or "").strip()
    if not last_url:
        return ()
    taken: list[SlimAction] = []
    for a in reversed(actions):
        u = (a.canonical_url or "").strip()
        if u == last_url:
            taken.append(a)
        else:
            break
    return tuple(reversed(taken))


def _run_duration_seconds(run: tuple[SlimAction, ...], now: float) -> float:
    if not run:
        return 0.0
    first, last = run[0], run[-1]
    span = float(last.timestamp_end) - float(first.timestamp_start)
    if span <= 0.0 and len(run) == 1:
        return max(0.0, now - float(first.timestamp_start))
    return max(0.0, span)


def _resolve_max_sparse_actions(extra: dict[str, Any], default: int) -> int:
    raw = extra.get("user_page_dwell_max_actions")
    if raw is None:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    if n <= 0:
        return default
    return n


class UserPageDwellTrigger:
    """Fires when the user stays on one canonical URL ≥ threshold with ≤ N actions (sparse)."""

    def __init__(
        self,
        *,
        default_threshold_s: float = DEFAULT_USER_PAGE_DWELL_THRESHOLD_S,
        default_max_actions: int = DEFAULT_USER_PAGE_DWELL_MAX_ACTIONS,
    ) -> None:
        self._default_threshold_s = default_threshold_s
        self._default_max_actions = default_max_actions

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_USER_PAGE_DWELL

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        extra: dict[str, Any] = ctx.context_extra or {}
        threshold = float(
            extra.get("dwell_threshold_seconds", self._default_threshold_s)
        )
        if threshold <= 0:
            return None
        max_actions = _resolve_max_sparse_actions(extra, self._default_max_actions)
        now = float(extra.get("eval_now", time.time()))
        run = _trailing_run_same_url(ctx.recent_actions)
        if not run:
            return None
        if len(run) > max_actions:
            return None
        dur = _run_duration_seconds(run, now)
        if dur < threshold:
            return None
        raw_body = (extra.get("dwell_proactive_body") or "").strip() or (
            "Still on this page — want a quick tip?"
        )
        body = validate_or_truncate_proactive_body(raw_body)
        return ProactiveTriggerResult(
            trigger_id=self.trigger_id,
            body=body,
            metadata={
                "user_page_dwell_seconds": round(dur, 3),
                "user_page_dwell_action_count": len(run),
                "user_page_dwell_max_actions": max_actions,
                "dwell_threshold_seconds": threshold,
                "user_page_dwell_canonical_url": (run[-1].canonical_url or "")[:512],
            },
        )
