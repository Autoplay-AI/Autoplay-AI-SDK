"""Tests for the autoplay_sdk.storage subsystem + session-snapshot model.

Covers: SessionSnapshot model round-trip + defensive from_dict, the sessions
index on UserAdoptionState, key builders, the in-memory / Redis (fakeredis) /
fan-out manager / write-only sink adapters, the session lifecycle helpers, and
the onboarding-summary prompt-input builder.
"""

from __future__ import annotations

import json
import math
import time

import httpx
import pytest
import respx

from autoplay_sdk.prompts import ONBOARDING_SUMMARY_PROMPT
from autoplay_sdk.storage import (
    InMemoryStorageAdapter,
    RedisStorageAdapter,
    StorageManager,
    build_agent_context,
    init_user_state,
    on_session_end,
    on_session_start,
    session_key,
    user_state_key,
)
from autoplay_sdk.storage.adapters.amplitude import AmplitudeStorageAdapter
from autoplay_sdk.storage.adapters.posthog import PostHogStorageAdapter
from autoplay_sdk.user_adoption_state import (
    COMPLETION_RATE_DENOMINATOR_ALL_CATALOG,
    JourneyState,
    SessionIndexEntry,
    SessionSnapshot,
    UserAdoptionState,
    WorkflowStatus,
    build_onboarding_summary_input,
)
from autoplay_sdk.user_adoption_state.models import _MAX_SESSION_INDEX


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _state(user_id: str = "u1") -> UserAdoptionState:
    s = UserAdoptionState(user_id=user_id)
    s.onboarding.upsert_workflow_progress(
        "w1", status=WorkflowStatus.COMPLETED, confidence=0.9
    )
    s.onboarding.upsert_workflow_progress(
        "w2", status=WorkflowStatus.IN_PROGRESS, confidence=0.5
    )
    return s


def _snapshot(
    state: UserAdoptionState | None = None,
    *,
    session_id: str = "sess-1",
    session_number: int = 1,
    catalog: list[str] | None = None,
) -> SessionSnapshot:
    state = state or _state()
    return SessionSnapshot.from_adoption_state(
        state,
        session_id=session_id,
        session_number=session_number,
        started_at=time.time() - 120,
        catalog_workflow_ids=catalog if catalog is not None else ["w1", "w2", "w3"],
    )


# ---------------------------------------------------------------------------
# SessionSnapshot model
# ---------------------------------------------------------------------------


class TestSessionSnapshot:
    def test_from_adoption_state_maps_workflows(self) -> None:
        snap = _snapshot()
        assert snap.completed_workflow_ids == ["w1"]
        assert snap.in_progress_workflow_ids == ["w2"]
        assert snap.untouched_workflow_ids == ["w3"]
        assert snap.total_catalog_workflows == 3
        assert snap.completion_rate == pytest.approx(1 / 3, abs=1e-4)
        assert (
            snap.completion_rate_denominator == COMPLETION_RATE_DENOMINATOR_ALL_CATALOG
        )
        assert snap._frozen is True

    def test_from_adoption_state_copies_workflow_progress(self) -> None:
        state = _state()
        snap = _snapshot(state)
        # Mutating the live state after capture must not change the frozen copy.
        state.onboarding.upsert_workflow_progress(
            "w1", status=WorkflowStatus.NOT_STARTED, confidence=0.0
        )
        assert snap.workflow_progress["w1"].status == WorkflowStatus.COMPLETED

    def test_roundtrip(self) -> None:
        snap = _snapshot()
        restored = SessionSnapshot.from_dict(snap.to_dict())
        assert restored.session_id == snap.session_id
        assert restored.completed_workflow_ids == snap.completed_workflow_ids
        assert restored.workflow_progress["w1"].status == WorkflowStatus.COMPLETED
        assert restored.journey_state == snap.journey_state

    def test_from_dict_defensive(self) -> None:
        snap = SessionSnapshot.from_dict(
            {
                "session_id": "s",
                "journey_state": "bogus",
                "completion_rate": "not-a-number",
                "completion_rate_denominator": "bogus",
                "started_at": float("nan"),
                "session_number": -4,
                "discovered_features": "not-a-list",
                "workflow_progress": "not-a-dict",
            }
        )
        assert snap.journey_state == JourneyState.ONBOARDING
        assert snap.completion_rate == 0.0
        assert (
            snap.completion_rate_denominator == COMPLETION_RATE_DENOMINATOR_ALL_CATALOG
        )
        assert math.isfinite(snap.started_at)
        assert snap.session_number == 0
        assert snap.discovered_features == []
        assert snap.workflow_progress == {}

    def test_from_dict_none(self) -> None:
        snap = SessionSnapshot.from_dict(None)
        assert snap.session_id == ""
        assert snap._frozen is True


# ---------------------------------------------------------------------------
# UserAdoptionState sessions index
# ---------------------------------------------------------------------------


class TestSessionsIndex:
    def test_record_session_caps_index_but_counts_all(self) -> None:
        s = UserAdoptionState(user_id="u1")
        total = _MAX_SESSION_INDEX + 10
        for i in range(total):
            s.record_session(
                SessionIndexEntry(
                    session_id=f"sess-{i}",
                    session_number=i + 1,
                    started_at=float(i),
                    captured_at=float(i),
                )
            )
        assert s.sessions_count == total
        assert len(s.sessions_index) == _MAX_SESSION_INDEX
        # The most recent entries are retained.
        assert s.sessions_index[-1].session_id == f"sess-{total - 1}"

    def test_roundtrip_preserves_sessions(self) -> None:
        s = UserAdoptionState(user_id="u1")
        s.set_current_session("sess-1")
        s.record_session(
            SessionIndexEntry(
                session_id="sess-1", session_number=1, started_at=1.0, captured_at=2.0
            )
        )
        restored = UserAdoptionState.from_dict(s.to_dict())
        assert restored.sessions_count == 1
        assert restored.current_session_id == "sess-1"
        assert restored.sessions_index[0].session_id == "sess-1"

    def test_from_dict_handles_corrupt_sessions(self) -> None:
        s = UserAdoptionState.from_dict(
            {"_v": 1, "user_id": "u1", "sessions": "not-a-dict"}
        )
        assert s.sessions_count == 0
        assert s.current_session_id is None
        assert s.sessions_index == []


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


class TestKeys:
    def test_user_state_key(self) -> None:
        assert user_state_key("p1", "u1") == "autoplay:user:p1:u1:state"

    def test_session_key(self) -> None:
        assert session_key("p1", "u1", "s1") == "autoplay:user:p1:u1:session:s1"


# ---------------------------------------------------------------------------
# InMemoryStorageAdapter
# ---------------------------------------------------------------------------


class TestInMemoryAdapter:
    async def test_user_state_roundtrip(self) -> None:
        a = InMemoryStorageAdapter()
        assert await a.get_user_state("p", "u") is None
        await a.save_user_state("p", "u", {"x": 1})
        assert await a.get_user_state("p", "u") == {"x": 1}

    async def test_user_state_is_copied(self) -> None:
        a = InMemoryStorageAdapter()
        payload = {"x": 1}
        await a.save_user_state("p", "u", payload)
        payload["x"] = 999
        assert (await a.get_user_state("p", "u"))["x"] == 1

    async def test_snapshot_write_once(self) -> None:
        a = InMemoryStorageAdapter()
        await a.save_session_snapshot("p", "u", "s", {"v": 1})
        await a.save_session_snapshot("p", "u", "s", {"v": 2})
        assert (await a.get_session_snapshot("p", "u", "s")) == {"v": 1}


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------


class _FailingAdapter:
    """Adapter whose every method raises — exercises the manager's resilience."""

    async def save_user_state(self, product_id: str, user_id: str, state: dict) -> None:
        raise RuntimeError("boom")

    async def get_user_state(self, product_id: str, user_id: str) -> dict | None:
        raise RuntimeError("boom")

    async def save_session_snapshot(
        self, product_id: str, user_id: str, session_id: str, snapshot: dict
    ) -> None:
        raise RuntimeError("boom")

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict | None:
        raise RuntimeError("boom")


class TestStorageManager:
    def test_requires_at_least_one_adapter(self) -> None:
        with pytest.raises(ValueError):
            StorageManager([])

    async def test_fanout_writes_to_all(self) -> None:
        a, b = InMemoryStorageAdapter(), InMemoryStorageAdapter()
        mgr = StorageManager([a, b])
        await mgr.save_user_state("p", "u", {"x": 1})
        assert await a.get_user_state("p", "u") == {"x": 1}
        assert await b.get_user_state("p", "u") == {"x": 1}

    async def test_read_returns_first_non_none(self) -> None:
        primary, secondary = InMemoryStorageAdapter(), InMemoryStorageAdapter()
        await secondary.save_user_state("p", "u", {"from": "secondary"})
        await primary.save_user_state("p", "u", {"from": "primary"})
        mgr = StorageManager([primary, secondary])
        assert (await mgr.get_user_state("p", "u")) == {"from": "primary"}

    async def test_read_falls_through_when_primary_empty(self) -> None:
        primary, secondary = InMemoryStorageAdapter(), InMemoryStorageAdapter()
        await secondary.save_user_state("p", "u", {"from": "secondary"})
        mgr = StorageManager([primary, secondary])
        assert (await mgr.get_user_state("p", "u")) == {"from": "secondary"}

    async def test_failing_sink_does_not_block_others(self) -> None:
        good = InMemoryStorageAdapter()
        mgr = StorageManager([good, _FailingAdapter()])
        await mgr.save_user_state("p", "u", {"x": 1})  # must not raise
        assert await good.get_user_state("p", "u") == {"x": 1}

    async def test_failing_read_is_skipped(self) -> None:
        good = InMemoryStorageAdapter()
        await good.save_user_state("p", "u", {"x": 1})
        mgr = StorageManager([_FailingAdapter(), good])
        assert (await mgr.get_user_state("p", "u")) == {"x": 1}


# ---------------------------------------------------------------------------
# RedisStorageAdapter (fakeredis)
# ---------------------------------------------------------------------------


def _redis_adapter() -> RedisStorageAdapter:
    import fakeredis.aioredis

    adapter = RedisStorageAdapter(redis_url="redis://localhost:6379/0")
    # Swap the live client for an in-memory fake (decode_responses to match).
    adapter._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return adapter


class TestRedisAdapter:
    async def test_user_state_roundtrip(self) -> None:
        a = _redis_adapter()
        assert await a.get_user_state("p", "u") is None
        await a.save_user_state("p", "u", {"x": 1})
        assert await a.get_user_state("p", "u") == {"x": 1}

    async def test_user_state_overwrites(self) -> None:
        a = _redis_adapter()
        await a.save_user_state("p", "u", {"v": 1})
        await a.save_user_state("p", "u", {"v": 2})
        assert (await a.get_user_state("p", "u")) == {"v": 2}

    async def test_snapshot_write_once(self) -> None:
        a = _redis_adapter()
        await a.save_session_snapshot("p", "u", "s", {"v": 1})
        await a.save_session_snapshot("p", "u", "s", {"v": 2})
        assert (await a.get_session_snapshot("p", "u", "s")) == {"v": 1}

    async def test_get_missing_returns_none(self) -> None:
        a = _redis_adapter()
        assert await a.get_session_snapshot("p", "u", "missing") is None


# ---------------------------------------------------------------------------
# Write-only sink adapters (respx)
# ---------------------------------------------------------------------------


_AMP_URL = "https://api2.amplitude.com/2/httpapi"


class TestAmplitudeSink:
    @respx.mock
    async def test_save_user_state_posts_identify(self) -> None:
        route = respx.post(_AMP_URL).mock(return_value=httpx.Response(200))
        adapter = AmplitudeStorageAdapter(api_key="key")
        await adapter.save_user_state("p1", "u1", _state().to_dict())
        assert route.called
        body = json.loads(route.calls.last.request.content)
        event = body["events"][0]
        assert body["api_key"] == "key"
        assert event["event_type"] == "$identify"
        props = event["user_properties"]["$set"]
        assert props["product_id"] == "p1"
        assert props["completed_workflows"] == ["w1"]
        assert props["in_progress_workflows"] == ["w2"]

    @respx.mock
    async def test_property_prefix(self) -> None:
        route = respx.post(_AMP_URL).mock(return_value=httpx.Response(200))
        adapter = AmplitudeStorageAdapter(api_key="key", property_prefix="ap")
        await adapter.save_user_state("p1", "u1", _state().to_dict())
        props = json.loads(route.calls.last.request.content)["events"][0][
            "user_properties"
        ]["$set"]
        assert "ap_journey_state" in props

    @respx.mock
    async def test_save_session_posts_event(self) -> None:
        route = respx.post(_AMP_URL).mock(return_value=httpx.Response(200))
        adapter = AmplitudeStorageAdapter(api_key="key")
        await adapter.save_session_snapshot("p1", "u1", "sess-1", _snapshot().to_dict())
        event = json.loads(route.calls.last.request.content)["events"][0]
        assert event["event_type"] == "autoplay_session_captured"
        assert event["event_properties"]["session_id"] == "sess-1"

    async def test_reads_return_none(self) -> None:
        adapter = AmplitudeStorageAdapter(api_key="key")
        assert await adapter.get_user_state("p", "u") is None
        assert await adapter.get_session_snapshot("p", "u", "s") is None

    @respx.mock
    async def test_best_effort_swallows_http_error(self) -> None:
        respx.post(_AMP_URL).mock(return_value=httpx.Response(500))
        adapter = AmplitudeStorageAdapter(api_key="key")
        # Must not raise even on a 5xx.
        await adapter.save_user_state("p1", "u1", _state().to_dict())

    @respx.mock
    async def test_best_effort_swallows_network_error(self) -> None:
        respx.post(_AMP_URL).mock(side_effect=httpx.ConnectError("down"))
        adapter = AmplitudeStorageAdapter(api_key="key")
        await adapter.save_user_state("p1", "u1", _state().to_dict())


class TestPostHogSink:
    @respx.mock
    async def test_save_user_state_posts_set(self) -> None:
        url = "https://app.posthog.com/capture/"
        route = respx.post(url).mock(return_value=httpx.Response(200))
        adapter = PostHogStorageAdapter(api_key="key")
        await adapter.save_user_state("p1", "u1", _state().to_dict())
        body = json.loads(route.calls.last.request.content)
        assert body["event"] == "$set"
        assert body["distinct_id"] == "u1"
        assert body["properties"]["$set"]["completed_workflows"] == ["w1"]

    @respx.mock
    async def test_custom_host_and_session_event(self) -> None:
        url = "https://eu.posthog.com/capture/"
        route = respx.post(url).mock(return_value=httpx.Response(200))
        adapter = PostHogStorageAdapter(api_key="key", host="https://eu.posthog.com/")
        await adapter.save_session_snapshot("p1", "u1", "sess-1", _snapshot().to_dict())
        body = json.loads(route.calls.last.request.content)
        assert body["event"] == "autoplay_session_captured"
        assert body["properties"]["session_id"] == "sess-1"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_init_user_state(self) -> None:
        s = init_user_state("u1", metadata={"role": "admin"})
        assert s.user_id == "u1"
        assert s.metadata["role"] == "admin"

    async def test_first_session_creates_and_persists(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, onboarding = await on_session_start("p", "u", "sess-1", storage)
        assert state.current_session_id == "sess-1"
        assert onboarding is None
        assert (await storage.get_user_state("p", "u")) is not None

    async def test_end_then_returning_session_loads_onboarding(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, _ = await on_session_start("p", "u", "sess-1", storage)
        snap = _snapshot(state, session_id="sess-1", session_number=1)
        await on_session_end("p", "u", snap, storage, summary="brief")

        state2, onboarding = await on_session_start("p", "u", "sess-2", storage)
        assert state2.sessions_count == 1
        assert state2.onboarding.summary == "brief"
        assert onboarding is not None
        assert onboarding.session_id == "sess-1"

    async def test_summarizer_is_used_when_no_summary(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, _ = await on_session_start("p", "u", "sess-1", storage)
        state.onboarding.upsert_workflow_progress(
            "w1", status=WorkflowStatus.COMPLETED, confidence=0.9
        )
        snap = _snapshot(state)

        async def summarizer(s: SessionSnapshot) -> str:
            return f"completed={len(s.completed_workflow_ids)}"

        out = await on_session_end("p", "u", snap, storage, summarizer=summarizer)
        assert out.onboarding.summary == "completed=1"

    async def test_explicit_summary_wins_over_summarizer(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, _ = await on_session_start("p", "u", "sess-1", storage)
        snap = _snapshot(state)

        async def summarizer(s: SessionSnapshot) -> str:
            raise AssertionError("summarizer should not be called")

        out = await on_session_end(
            "p", "u", snap, storage, summarizer=summarizer, summary="explicit"
        )
        assert out.onboarding.summary == "explicit"

    async def test_summarizer_failure_does_not_lose_session(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, _ = await on_session_start("p", "u", "sess-1", storage)
        snap = _snapshot(state)

        async def summarizer(s: SessionSnapshot) -> str:
            raise RuntimeError("llm down")

        out = await on_session_end("p", "u", snap, storage, summarizer=summarizer)
        assert out.sessions_count == 1
        assert out.onboarding.summary is None
        assert (await storage.get_session_snapshot("p", "u", "sess-1")) is not None

    async def test_session_end_is_write_once_for_snapshot(self) -> None:
        storage = StorageManager([InMemoryStorageAdapter()])
        state, _ = await on_session_start("p", "u", "sess-1", storage)
        first = _snapshot(state, session_id="sess-1")
        await on_session_end("p", "u", first, storage, summary="first")
        # A duplicate session-end for the same id must not overwrite the snapshot.
        second = _snapshot(state, session_id="sess-1")
        second.completion_rate = 0.99
        await on_session_end("p", "u", second, storage, summary="second")
        stored = await storage.get_session_snapshot("p", "u", "sess-1")
        assert stored["completion_rate"] == first.completion_rate

    def test_build_agent_context(self) -> None:
        s = _state()
        s.sessions_count = 2
        s.onboarding.summary = "did things"
        onboarding = _snapshot(s)
        ctx = build_agent_context(s, onboarding)
        assert ctx["session_count"] == 2
        assert ctx["is_returning_user"] is True
        assert ctx["onboarding_summary"] == "did things"
        assert ctx["onboarding_session_in_progress_workflows"] == ["w2"]
        assert ctx["onboarding_session_untouched_workflows"] == ["w3"]

    def test_build_agent_context_minimal(self) -> None:
        ctx = build_agent_context(UserAdoptionState(user_id="u1"))
        assert ctx["session_count"] == 0
        assert ctx["is_returning_user"] is False
        assert "onboarding_summary" not in ctx


# ---------------------------------------------------------------------------
# Onboarding summary prompt-input builder
# ---------------------------------------------------------------------------


class TestSummaryPromptBuilder:
    def test_keys_present(self) -> None:
        inp = build_onboarding_summary_input(_snapshot())
        for key in (
            "session_number",
            "duration_minutes",
            "journey_state",
            "mastery_level",
            "mastery_rating",
            "completion_rate",
            "completed_workflow_ids_json",
            "in_progress_workflow_ids_json",
            "untouched_workflow_ids_json",
            "discovered_features_json",
        ):
            assert key in inp

    def test_lists_are_json_encoded(self) -> None:
        inp = build_onboarding_summary_input(_snapshot())
        assert json.loads(inp["completed_workflow_ids_json"]) == ["w1"]
        assert json.loads(inp["in_progress_workflow_ids_json"]) == ["w2"]

    def test_input_fills_prompt_template(self) -> None:
        inp = build_onboarding_summary_input(_snapshot())
        rendered = ONBOARDING_SUMMARY_PROMPT["content"].format(**inp)
        assert "session_number:" in rendered
