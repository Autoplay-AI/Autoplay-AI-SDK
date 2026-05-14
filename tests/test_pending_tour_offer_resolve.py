"""Tests for Redis pending tour value encoding."""

from __future__ import annotations

from autoplay_sdk.proactive_triggers.pending_tour_offer import (
    pending_offer_to_json,
    resolve_pending_redis_value,
)


def test_legacy_one_maps_to_default() -> None:
    assert resolve_pending_redis_value("1", default_flow_id="abc") == "abc"


def test_json_flow_id() -> None:
    raw = pending_offer_to_json("cm123")
    assert resolve_pending_redis_value(raw, default_flow_id="fallback") == "cm123"


def test_missing_raw_uses_default() -> None:
    assert resolve_pending_redis_value(None, default_flow_id="z") == "z"
