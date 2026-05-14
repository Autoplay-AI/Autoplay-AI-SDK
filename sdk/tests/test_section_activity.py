"""Tests for product_section_playbook aggregation and playbook resolution."""

from __future__ import annotations

from autoplay_sdk.models import SlimAction
from autoplay_sdk.proactive_triggers.section_activity import (
    build_product_section_playbook,
    resolve_section_id,
    resolve_section_id_for_playbook,
    top_playbook_section_id,
    total_dwell_seconds,
)
from autoplay_sdk.proactive_triggers.triggers.section_playbook import (
    SectionPlaybookTrigger,
)
from autoplay_sdk.proactive_triggers.types import ProactiveTriggerContext


def _action(
    *,
    url: str,
    ts_start: float,
    ts_end: float,
) -> SlimAction:
    return SlimAction(
        title="t",
        description="d",
        canonical_url=url,
        timestamp_start=ts_start,
        timestamp_end=ts_end,
    )


def test_resolve_section_id_first_prefix_wins() -> None:
    rules = (
        {"prefix": "/a", "section_id": "A"},
        {"prefix": "/a/b", "section_id": "AB"},
    )
    assert resolve_section_id("/a/b/c", rules) == "A"


def test_build_product_section_playbook_visits_and_dwell() -> None:
    rules = ({"prefix": "/pricing", "section_id": "pricing"},)
    actions = (
        _action(url="/pricing", ts_start=100.0, ts_end=110.0),
        _action(url="/pricing", ts_start=110.0, ts_end=125.0),
        _action(url="/checkout", ts_start=126.0, ts_end=130.0),
        _action(url="/pricing", ts_start=131.0, ts_end=140.0),
    )
    psp = build_product_section_playbook(actions, rules=rules, fallback_id="other")
    assert psp["runtime"]["current_section_id"] == "pricing"
    pr = psp["sections"]["pricing"]
    assert pr["visit_count"] == 2
    assert pr["dwell_seconds_per_visit"] == [25.0, 9.0]
    # ``/checkout`` does not match ``/pricing`` — buckets into fallback ``other``.
    assert psp["sections"]["other"]["dwell_seconds_per_visit"] == [4.0]


def test_top_playbook_section_id_prefers_total_dwell() -> None:
    psp = {
        "runtime": {"current_section_id": "checkout"},
        "sections": {
            "pricing": {"visit_count": 1, "dwell_seconds_per_visit": [100.0]},
            "checkout": {"visit_count": 2, "dwell_seconds_per_visit": [10.0, 20.0]},
        },
    }
    book = {"pricing": "x", "checkout": "y"}
    assert top_playbook_section_id(psp, book) == "pricing"


def test_resolve_section_id_for_playbook_host_override() -> None:
    extra = {
        "current_section_id": "checkout",
        "section_playbook": {"pricing": "a", "checkout": "b"},
        "product_section_playbook": {
            "runtime": {"current_section_id": "pricing"},
            "sections": {
                "pricing": {"visit_count": 1, "dwell_seconds_per_visit": [99.0]},
            },
        },
    }
    assert resolve_section_id_for_playbook(extra) == "checkout"


def test_section_playbook_trigger_uses_ranked_id() -> None:
    ctx = ProactiveTriggerContext(
        session_id="s",
        conversation_id="c",
        product_id="p",
        context_extra={
            "section_playbook": {"pricing": "Hello", "checkout": "Bye"},
            "product_section_playbook": {
                "runtime": {"current_section_id": "checkout"},
                "sections": {
                    "pricing": {"visit_count": 1, "dwell_seconds_per_visit": [50.0]},
                    "checkout": {"visit_count": 1, "dwell_seconds_per_visit": [5.0]},
                },
            },
        },
    )
    r = SectionPlaybookTrigger().evaluate(ctx)
    assert r is not None
    assert r.body == "Hello"
    assert r.metadata.get("section_id") == "pricing"


def test_total_dwell_seconds() -> None:
    assert total_dwell_seconds({"dwell_seconds_per_visit": [1.5, 2.5]}) == 4.0
