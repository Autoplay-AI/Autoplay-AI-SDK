"""Tests for autoplay_sdk.rag_query.watermark."""

from __future__ import annotations

import pytest

from autoplay_sdk.rag_query.watermark import (
    ChatWatermarkScope,
    InMemoryInboundWatermarkStore,
    cutoff_for_delta_activity,
    effective_inbound_timestamp,
)


@pytest.mark.asyncio
async def test_in_memory_watermark_round_trip() -> None:
    store = InMemoryInboundWatermarkStore()
    scope = ChatWatermarkScope(conversation_id="c1", product_id="p1")

    assert await store.get_previous_inbound_at(scope) is None

    await store.set_last_inbound_at(scope, 1000.0)
    assert await store.get_previous_inbound_at(scope) == 1000.0

    await store.set_last_inbound_at(scope, 2000.0)
    assert await store.get_previous_inbound_at(scope) == 2000.0


@pytest.mark.asyncio
async def test_in_memory_scope_isolation() -> None:
    store = InMemoryInboundWatermarkStore()
    s1 = ChatWatermarkScope(conversation_id="a", product_id="p")
    s2 = ChatWatermarkScope(conversation_id="b", product_id="p")

    await store.set_last_inbound_at(s1, 1.0)
    await store.set_last_inbound_at(s2, 2.0)

    assert await store.get_previous_inbound_at(s1) == 1.0
    assert await store.get_previous_inbound_at(s2) == 2.0


def test_cutoff_for_delta_activity_is_passthrough() -> None:
    assert cutoff_for_delta_activity(None) is None
    assert cutoff_for_delta_activity(123.45) == 123.45


def test_effective_inbound_timestamp() -> None:
    assert effective_inbound_timestamp(99.0) == 99.0
    assert effective_inbound_timestamp(None, fallback=42.0) == 42.0
