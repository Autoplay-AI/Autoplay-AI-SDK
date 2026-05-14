"""Tests for UserPageDwellTrigger (sparse same-URL streak)."""

from __future__ import annotations

import time

from autoplay_sdk.models import SlimAction
from autoplay_sdk.proactive_triggers.defaults import TRIGGER_ID_USER_PAGE_DWELL
from autoplay_sdk.proactive_triggers.types import ProactiveTriggerContext
from autoplay_sdk.proactive_triggers.triggers.user_page_dwell import (
    UserPageDwellTrigger,
)


def _action(
    url: str,
    t0: float,
    t1: float | None = None,
) -> SlimAction:
    return SlimAction(
        title="p",
        description="",
        canonical_url=url,
        index=0,
        type="pageview",
        timestamp_start=t0,
        timestamp_end=t1 if t1 is not None else t0,
    )


def test_user_page_dwell_fires_60s_sparse() -> None:
    t = UserPageDwellTrigger()
    now = 1_000_000.0
    # 2 actions, same URL, 70s span
    a0 = _action("https://app/x", now - 70.0, now - 70.0)
    a1 = _action("https://app/x", now - 1.0, now)
    c = ProactiveTriggerContext.from_slim_actions(
        [a0, a1],
        product_id="p",
        session_id="s",
        context_extra={
            "eval_now": now,
            "dwell_threshold_seconds": 60,
            "user_page_dwell_max_actions": 5,
        },
    )
    r = t.evaluate(c)
    assert r is not None
    assert r.trigger_id == TRIGGER_ID_USER_PAGE_DWELL
    assert r.metadata.get("user_page_dwell_action_count") == 2
    assert r.metadata.get("user_page_dwell_max_actions") == 5
    assert r.metadata.get("user_page_dwell_seconds", 0) >= 60


def test_user_page_dwell_too_many_actions() -> None:
    t = UserPageDwellTrigger()
    now = 2_000_000.0
    base = now - 120.0
    # 6 actions on same URL > default max 5
    acts = [
        _action("https://app/y", base + i * 10, base + i * 10 + 1) for i in range(6)
    ]
    c = ProactiveTriggerContext.from_slim_actions(
        acts,
        product_id="p",
        session_id="s",
        context_extra={
            "eval_now": now + 100,
            "dwell_threshold_seconds": 60,
            "user_page_dwell_max_actions": 5,
        },
    )
    assert t.evaluate(c) is None


def test_user_page_dwell_under_threshold_time() -> None:
    t = UserPageDwellTrigger()
    now = time.time()
    a0 = _action("https://app/z", now - 30.0, now - 30.0)
    a1 = _action("https://app/z", now - 1.0, now)
    c = ProactiveTriggerContext.from_slim_actions(
        [a0, a1],
        product_id="p",
        session_id="s",
        context_extra={
            "eval_now": now,
            "dwell_threshold_seconds": 60,
        },
    )
    assert t.evaluate(c) is None


def test_catalog_contains_user_page_dwell() -> None:
    from autoplay_sdk.proactive_triggers.builtin_catalog import BUILTIN_TRIGGER_CATALOG

    assert TRIGGER_ID_USER_PAGE_DWELL in BUILTIN_TRIGGER_CATALOG
