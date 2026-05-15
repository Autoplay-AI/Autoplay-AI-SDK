"""Tests for autoplay_sdk.context_store — ContextStore and AsyncContextStore."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.context_store import (  # noqa: E402
    AsyncContextStore,
    ContextStore,
    actions_bucket_id,
)
from autoplay_sdk.models import ActionsPayload, SlimAction  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = time.time()


def _action(
    session_id: str = "sess1",
    n: int = 1,
    forwarded_at: float | None = None,
) -> ActionsPayload:
    actions = [
        SlimAction(
            title=f"A{i}", description=f"Did thing {i}", canonical_url=f"/page/{i}"
        )
        for i in range(n)
    ]
    return ActionsPayload(
        product_id="",
        session_id=session_id,
        user_id=None,
        email=None,
        actions=actions,
        count=n,
        forwarded_at=forwarded_at if forwarded_at is not None else _NOW,
    )


# ---------------------------------------------------------------------------
# ContextStore — basic add / on_summary / get / enrich
# ---------------------------------------------------------------------------


class TestContextStoreBasics:
    def test_enrich_returns_query_unchanged_when_no_context(self):
        store = ContextStore()
        assert store.enrich("sess1", "What is X?") == "What is X?"

    def test_get_returns_empty_when_no_context(self):
        store = ContextStore()
        assert store.get("sess1") == ""

    def test_add_stores_actions_and_get_returns_them(self):
        store = ContextStore()
        store.add(_action("s1", n=2))
        result = store.get("s1")
        assert "Recent activity:" in result
        assert "Did thing 0" in result
        assert "Did thing 1" in result

    def test_on_summary_stores_summary_and_get_returns_it(self):
        store = ContextStore()
        store.on_summary("s1", "User browsed the dashboard.")
        result = store.get("s1")
        assert "Summary: User browsed the dashboard." in result

    def test_get_combines_summary_and_actions(self):
        store = ContextStore()
        store.on_summary("s1", "Previously: exported CSV.")
        store.add(_action("s1", n=1))
        result = store.get("s1")
        assert "Summary:" in result
        assert "Recent activity:" in result

    def test_enrich_wraps_context_and_query(self):
        store = ContextStore()
        store.on_summary("s1", "User browsed dashboard.")
        result = store.enrich("s1", "How do I export?")
        assert "[Session context]" in result
        assert "[Query]" in result
        assert "How do I export?" in result
        assert "User browsed dashboard." in result

    def test_enrich_returns_raw_query_when_context_empty(self):
        store = ContextStore()
        result = store.enrich("s1", "Hello?")
        assert result == "Hello?"

    def test_sessions_are_independent(self):
        store = ContextStore()
        store.add(_action("alice", n=1))
        store.on_summary("bob", "Bob did stuff.")
        assert "Recent activity:" in store.get("alice")
        assert store.get("alice").count("Summary:") == 0
        assert "Summary: Bob did stuff." in store.get("bob")
        assert "Recent activity:" not in store.get("bob")

    def test_none_session_id_stored_as_unknown(self):
        store = ContextStore()
        payload = _action(n=1)
        payload.session_id = None
        store.add(payload)
        result = store.get("unknown")
        assert "Recent activity:" in result

    def test_multiple_adds_accumulate(self):
        store = ContextStore()
        store.add(_action("s1", n=1))
        store.add(_action("s1", n=1))
        result = store.get("s1")
        # Two separate payloads → two lines
        assert "1." in result
        assert "2." in result


# ---------------------------------------------------------------------------
# include_summary / include_actions toggles
# ---------------------------------------------------------------------------


class TestContextStoreToggles:
    def test_include_summary_false_omits_summary(self):
        store = ContextStore(include_summary=False)
        store.on_summary("s1", "Some summary.")
        store.add(_action("s1", n=1))
        result = store.get("s1")
        assert "Summary:" not in result
        assert "Recent activity:" in result

    def test_include_actions_false_omits_actions(self):
        store = ContextStore(include_actions=False)
        store.on_summary("s1", "Some summary.")
        store.add(_action("s1", n=1))
        result = store.get("s1")
        assert "Summary:" in result
        assert "Recent activity:" not in result

    def test_both_false_returns_empty(self):
        store = ContextStore(include_summary=False, include_actions=False)
        store.on_summary("s1", "Summary.")
        store.add(_action("s1", n=1))
        assert store.get("s1") == ""

    def test_per_call_include_summary_override(self):
        store = ContextStore(include_summary=True)
        store.on_summary("s1", "Summary.")
        store.add(_action("s1", n=1))
        result = store.get("s1", include_summary=False)
        assert "Summary:" not in result
        assert "Recent activity:" in result

    def test_per_call_include_actions_override(self):
        store = ContextStore(include_actions=True)
        store.on_summary("s1", "Summary.")
        store.add(_action("s1", n=1))
        result = store.get("s1", include_actions=False)
        assert "Summary:" in result
        assert "Recent activity:" not in result

    def test_per_call_override_does_not_affect_default(self):
        store = ContextStore(include_summary=True)
        store.on_summary("s1", "Summary.")
        store.get("s1", include_summary=False)
        # Default should still be True
        assert "Summary:" in store.get("s1")


# ---------------------------------------------------------------------------
# max_actions
# ---------------------------------------------------------------------------


class TestContextStoreMaxActions:
    def test_max_actions_limits_output(self):
        store = ContextStore(max_actions=2)
        store.add(_action("s1", n=5))
        result = store.get("s1")
        # Only 2 actions → lines "1." and "2." but not "3."
        assert "1." in result
        assert "2." in result
        assert "3." not in result

    def test_max_actions_across_multiple_payloads(self):
        store = ContextStore(max_actions=3)
        store.add(_action("s1", n=2))
        store.add(_action("s1", n=2))
        result = store.get("s1")
        assert "1." in result
        assert "2." in result
        assert "3." in result
        assert "4." not in result

    def test_max_actions_none_returns_all(self):
        store = ContextStore(max_actions=None)
        store.add(_action("s1", n=10))
        result = store.get("s1")
        assert "10." in result

    def test_per_call_max_actions_override(self):
        store = ContextStore(max_actions=10)
        store.add(_action("s1", n=5))
        result = store.get("s1", max_actions=2)
        assert "2." in result
        assert "3." not in result

    def test_max_actions_larger_than_available_returns_all(self):
        store = ContextStore(max_actions=100)
        store.add(_action("s1", n=3))
        result = store.get("s1")
        assert "3." in result
        assert "4." not in result


# ---------------------------------------------------------------------------
# lookback_seconds
# ---------------------------------------------------------------------------


class TestContextStoreLookback:
    def test_lookback_filters_old_actions(self):
        store = ContextStore(lookback_seconds=60)
        old_ts = time.time() - 120  # 2 minutes ago
        store.add(_action("s1", n=1, forwarded_at=old_ts))
        result = store.get("s1")
        assert "Recent activity:" not in result

    def test_lookback_keeps_recent_actions(self):
        store = ContextStore(lookback_seconds=60)
        store.add(_action("s1", n=1, forwarded_at=time.time() - 10))
        result = store.get("s1")
        assert "Recent activity:" in result

    def test_lookback_filters_mixed_payloads(self):
        store = ContextStore(lookback_seconds=60)
        store.add(_action("s1", n=1, forwarded_at=time.time() - 120))  # old
        store.add(_action("s1", n=1, forwarded_at=time.time() - 10))  # recent
        result = store.get("s1")
        assert "1." in result
        assert "2." not in result  # only 1 recent action

    def test_lookback_none_returns_all(self):
        store = ContextStore(lookback_seconds=None)
        store.add(_action("s1", n=1, forwarded_at=time.time() - 99999))
        assert "Recent activity:" in store.get("s1")

    def test_per_call_lookback_override(self):
        store = ContextStore(lookback_seconds=None)
        store.add(_action("s1", n=1, forwarded_at=time.time() - 120))
        result = store.get("s1", lookback_seconds=60)
        assert "Recent activity:" not in result

    def test_lookback_and_max_actions_combined(self):
        store = ContextStore(lookback_seconds=60, max_actions=1)
        store.add(_action("s1", n=3, forwarded_at=time.time() - 10))
        result = store.get("s1")
        assert "1." in result
        assert "2." not in result


# ---------------------------------------------------------------------------
# reset / active_sessions
# ---------------------------------------------------------------------------


class TestContextStoreReset:
    def test_reset_clears_actions_and_summary(self):
        store = ContextStore()
        store.add(_action("s1", n=1))
        store.on_summary("s1", "Summary.")
        store.reset("s1")
        assert store.get("s1") == ""

    def test_reset_unknown_session_does_not_raise(self):
        store = ContextStore()
        store.reset("does_not_exist")  # must not raise

    def test_active_sessions_includes_sessions_with_actions(self):
        store = ContextStore()
        store.add(_action("alice", n=1))
        store.add(_action("bob", n=1))
        assert set(store.active_sessions) >= {"alice", "bob"}

    def test_active_sessions_includes_sessions_with_only_summary(self):
        store = ContextStore()
        store.on_summary("charlie", "Summary.")
        assert "charlie" in store.active_sessions

    def test_active_sessions_empty_after_reset(self):
        store = ContextStore()
        store.add(_action("s1", n=1))
        store.reset("s1")
        assert "s1" not in store.active_sessions


# ---------------------------------------------------------------------------
# Summarizer wiring
# ---------------------------------------------------------------------------


class TestContextStoreSummarizerWiring:
    def test_wires_on_summary_when_summarizer_provided(self):
        summarizer = MagicMock()
        summarizer.on_summary = None
        store = ContextStore(summarizer=summarizer)  # noqa: F841
        # Bound methods are created fresh on each access, so compare via __func__
        assert summarizer.on_summary.__func__ is ContextStore.on_summary

    def test_warns_when_overwriting_existing_on_summary(self, caplog):
        import logging

        summarizer = MagicMock()
        summarizer.on_summary = MagicMock()
        with caplog.at_level(logging.WARNING, logger="autoplay_sdk.context_store"):
            ContextStore(summarizer=summarizer)
        assert "replacing existing on_summary" in caplog.text

    def test_summary_captured_via_wired_callback(self):
        summarizer = MagicMock()
        summarizer.on_summary = None
        store = ContextStore(summarizer=summarizer)
        # Simulate the summarizer firing its callback
        store.on_summary("s1", "Auto-captured summary.")
        assert "Auto-captured summary." in store.get("s1")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestContextStoreThreadSafety:
    def test_concurrent_adds_do_not_corrupt_state(self):
        store = ContextStore()
        errors: list[Exception] = []

        def writer(session_id: str) -> None:
            try:
                for _ in range(50):
                    store.add(_action(session_id, n=1))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(f"s{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_reads_and_writes_do_not_raise(self):
        store = ContextStore()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(50):
                    store.add(_action("shared", n=1))
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(50):
                    store.get("shared")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(3)] + [
            threading.Thread(target=reader) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# AsyncContextStore
# ---------------------------------------------------------------------------


class TestAsyncContextStore:
    @pytest.mark.asyncio
    async def test_add_stores_actions(self):
        store = AsyncContextStore()
        await store.add(_action("s1", n=2))
        assert "Recent activity:" in store.get("s1")

    @pytest.mark.asyncio
    async def test_on_summary_stores_summary(self):
        store = AsyncContextStore()
        await store.on_summary("s1", "Async summary.")
        assert "Async summary." in store.get("s1")

    @pytest.mark.asyncio
    async def test_enrich_returns_query_unchanged_when_no_context(self):
        store = AsyncContextStore()
        assert store.enrich("s1", "What?") == "What?"

    @pytest.mark.asyncio
    async def test_enrich_combines_summary_and_actions(self):
        store = AsyncContextStore()
        await store.on_summary("s1", "Previously exported CSV.")
        await store.add(_action("s1", n=1))
        result = store.enrich("s1", "How do I share?")
        assert "[Session context]" in result
        assert "[Query]" in result
        assert "Previously exported CSV." in result

    @pytest.mark.asyncio
    async def test_include_summary_false(self):
        store = AsyncContextStore(include_summary=False)
        await store.on_summary("s1", "Summary.")
        await store.add(_action("s1", n=1))
        assert "Summary:" not in store.get("s1")

    @pytest.mark.asyncio
    async def test_include_actions_false(self):
        store = AsyncContextStore(include_actions=False)
        await store.on_summary("s1", "Summary.")
        await store.add(_action("s1", n=1))
        assert "Recent activity:" not in store.get("s1")

    @pytest.mark.asyncio
    async def test_max_actions(self):
        store = AsyncContextStore(max_actions=2)
        await store.add(_action("s1", n=5))
        result = store.get("s1")
        assert "2." in result
        assert "3." not in result

    @pytest.mark.asyncio
    async def test_lookback_seconds_filters_old(self):
        store = AsyncContextStore(lookback_seconds=60)
        await store.add(_action("s1", n=1, forwarded_at=time.time() - 120))
        assert "Recent activity:" not in store.get("s1")

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        store = AsyncContextStore()
        await store.add(_action("s1", n=1))
        store.reset("s1")
        assert store.get("s1") == ""

    @pytest.mark.asyncio
    async def test_wires_on_summary_to_async_summarizer(self):
        summarizer = MagicMock()
        summarizer.on_summary = None
        store = AsyncContextStore(summarizer=summarizer)  # noqa: F841
        # Bound methods are created fresh on each access, so compare via __func__
        assert summarizer.on_summary.__func__ is AsyncContextStore.on_summary

    @pytest.mark.asyncio
    async def test_per_call_overrides(self):
        store = AsyncContextStore(include_summary=True, include_actions=True)
        await store.on_summary("s1", "Summary.")
        await store.add(_action("s1", n=3))
        # Override: summaries only
        result = store.enrich("s1", "Q?", include_actions=False)
        assert "Summary:" in result
        assert "Recent activity:" not in result
        # Override: last 1 action only
        result = store.enrich("s1", "Q?", max_actions=1)
        assert "1." in result
        assert "2." not in result


def test_product_scoped_action_buckets_isolate_same_session_string() -> None:
    store = ContextStore()
    pa = _action("sess_dup", n=1)
    pa.product_id = "tenant_a"
    pa.actions[0].canonical_url = "/tenant-a-only"
    pb = _action("sess_dup", n=1)
    pb.product_id = "tenant_b"
    pb.actions[0].canonical_url = "/tenant-b-only"
    store.add(pa)
    store.add(pb)
    assert actions_bucket_id("tenant_a", "sess_dup") != actions_bucket_id(
        "tenant_b", "sess_dup"
    )
    ga = store.get("sess_dup", product_id="tenant_a")
    gb = store.get("sess_dup", product_id="tenant_b")
    assert "/tenant-a-only" in ga
    assert "/tenant-b-only" in gb
    assert "/tenant-b-only" not in ga


def test_get_without_product_id_falls_back_to_single_product_bucket(caplog) -> None:
    import logging

    store = ContextStore()
    payload = _action("sess_single", n=1)
    payload.product_id = "tenant_x"
    payload.actions[0].description = "Scoped action"
    store.add(payload)

    with caplog.at_level(logging.WARNING, logger="autoplay_sdk.context_store"):
        result = store.get("sess_single")
    assert "Scoped action" in result
    assert "fell back to product-scoped actions bucket" in caplog.text


def test_get_without_product_id_warns_on_ambiguous_scoped_buckets(caplog) -> None:
    import logging

    store = ContextStore()
    payload_a = _action("sess_ambiguous", n=1)
    payload_a.product_id = "tenant_a"
    payload_b = _action("sess_ambiguous", n=1)
    payload_b.product_id = "tenant_b"
    store.add(payload_a)
    store.add(payload_b)

    with caplog.at_level(logging.WARNING, logger="autoplay_sdk.context_store"):
        result = store.get("sess_ambiguous")
    assert result == ""
    assert "found multiple product-scoped buckets" in caplog.text
