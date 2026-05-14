"""Tests for autoplay_sdk.proactive_triggers registry and triggers."""

from __future__ import annotations

import pytest
from autoplay_sdk.integrations.intercom import (
    INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY,
)
from autoplay_sdk.models import ActionsPayload, SlimAction
from autoplay_sdk.proactive_triggers import (
    CanonicalPingPongTrigger,
    PredicateProactiveTrigger,
    ProactiveScope,
    ProactiveTriggerContext,
    ProactiveTriggerEntity,
    ProactiveTriggerRegistry,
    ProactiveTriggerTimings,
    ScopePolicy,
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
    default_proactive_trigger_registry,
    get_proactive_trigger_ids,
)
from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_INTERACTION_TIMEOUT_S,
    DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S,
    DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS,
)
from autoplay_sdk.proactive_triggers.triggers.canonical_ping_pong import (
    TRIGGER_ID_CANONICAL_URL_PING_PONG as TID_PING_PONG,
)


def test_trigger_id_constant_stable() -> None:
    assert TRIGGER_ID_CANONICAL_URL_PING_PONG == "canonical_url_ping_pong"
    assert TID_PING_PONG == TRIGGER_ID_CANONICAL_URL_PING_PONG
    assert (
        get_proactive_trigger_ids().canonical_ping_pong
        == TRIGGER_ID_CANONICAL_URL_PING_PONG
    )


def test_canonical_ping_pong_trigger_returns_result_when_firing() -> None:
    t = CanonicalPingPongTrigger()
    ctx = ProactiveTriggerContext(canonical_urls=["/a", "/b", "/a"])
    r = t.evaluate(ctx)
    assert r is not None
    assert r.trigger_id == TRIGGER_ID_CANONICAL_URL_PING_PONG
    assert r.body == INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY
    assert r.metadata.get("min_cycles") == 1
    assert r.interaction_timeout_s == DEFAULT_INTERACTION_TIMEOUT_S
    assert r.cooldown_s == DEFAULT_COOLDOWN_S


def test_canonical_ping_pong_trigger_returns_none_when_no_fire() -> None:
    t = CanonicalPingPongTrigger()
    ctx = ProactiveTriggerContext(canonical_urls=["/a", "/b", "/c"])
    assert t.evaluate(ctx) is None


def test_registry_evaluate_first_order() -> None:
    hits: list[str] = []

    class A:
        trigger_id = "a"

        def evaluate(self, ctx: ProactiveTriggerContext):
            hits.append("a")
            return None

    class B:
        trigger_id = "b"

        def evaluate(self, ctx: ProactiveTriggerContext):
            hits.append("b")
            from autoplay_sdk.proactive_triggers.types import ProactiveTriggerResult

            return ProactiveTriggerResult(trigger_id="b", body="hi")

    reg = ProactiveTriggerRegistry([A(), B()])
    out = reg.evaluate_first(ProactiveTriggerContext())
    assert out is not None
    assert out.trigger_id == "b"
    assert hits == ["a", "b"]


def test_registry_evaluate_first_returns_first_hit() -> None:
    from autoplay_sdk.proactive_triggers.types import ProactiveTriggerResult

    class First:
        trigger_id = "first"

        def evaluate(self, ctx: ProactiveTriggerContext):
            return ProactiveTriggerResult(trigger_id="first", body="x")

    class Second:
        trigger_id = "second"

        def evaluate(self, ctx: ProactiveTriggerContext):
            return ProactiveTriggerResult(trigger_id="second", body="y")

    reg = ProactiveTriggerRegistry([First(), Second()])
    out = reg.evaluate_first(ProactiveTriggerContext())
    assert out is not None
    assert out.trigger_id == "first"


def test_registry_evaluate_all() -> None:
    from autoplay_sdk.proactive_triggers.types import ProactiveTriggerResult

    class T:
        trigger_id = "t"

        def evaluate(self, ctx: ProactiveTriggerContext):
            return ProactiveTriggerResult(trigger_id="t", body="one")

    reg = ProactiveTriggerRegistry([T(), T()])
    all_hits = reg.evaluate_all(ProactiveTriggerContext())
    assert len(all_hits) == 2


def test_default_registry_includes_ping_pong_entity() -> None:
    reg = default_proactive_trigger_registry()
    assert len(reg.triggers) == 1
    ent = reg.triggers[0]
    assert isinstance(ent, ProactiveTriggerEntity)
    assert ent.trigger_id == TRIGGER_ID_CANONICAL_URL_PING_PONG
    ctx = ProactiveTriggerContext(canonical_urls=["/a", "/b", "/a"])
    r = reg.evaluate_first(ctx)
    assert r is not None
    assert r.interaction_timeout_s == DEFAULT_INTERACTION_TIMEOUT_S
    assert r.cooldown_s == DEFAULT_COOLDOWN_S


def test_proactive_trigger_entity_overrides_timings() -> None:
    inner = CanonicalPingPongTrigger()
    entity = ProactiveTriggerEntity(
        inner,
        ProactiveTriggerTimings(interaction_timeout_s=7.5, cooldown_s=42.0),
    )
    ctx = ProactiveTriggerContext(canonical_urls=["/a", "/b", "/a"])
    r = entity.evaluate(ctx)
    assert r is not None
    assert r.interaction_timeout_s == 7.5
    assert r.cooldown_s == 42.0
    assert r.body == INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY


def test_predicate_trigger_fires_when_true() -> None:
    t = PredicateProactiveTrigger(
        trigger_id="custom_x",
        body="Hello",
        predicate=lambda ctx: ctx.action_count >= 3,
    )
    assert t.evaluate(ProactiveTriggerContext(action_count=2)) is None
    r = t.evaluate(ProactiveTriggerContext(action_count=3))
    assert r is not None
    assert r.trigger_id == "custom_x"
    assert r.body == "Hello"
    assert r.metadata == {}


def test_predicate_trigger_static_metadata() -> None:
    t = PredicateProactiveTrigger(
        trigger_id="m",
        body="b",
        predicate=lambda _: True,
        metadata={"k": 1},
    )
    r = t.evaluate(ProactiveTriggerContext())
    assert r is not None
    assert r.metadata == {"k": 1}


def test_predicate_trigger_metadata_fn_wins_over_static() -> None:
    t = PredicateProactiveTrigger(
        trigger_id="m",
        body="b",
        predicate=lambda ctx: ctx.session_id == "s1",
        metadata={"static": True},
        metadata_fn=lambda ctx: {"sid": ctx.session_id},
    )
    r = t.evaluate(ProactiveTriggerContext(session_id="s1"))
    assert r is not None
    assert r.metadata == {"sid": "s1"}
    assert "static" not in r.metadata


def test_predicate_trigger_sees_recent_actions() -> None:
    a = SlimAction(title="t", description="d", canonical_url="/x")

    def pred(ctx: ProactiveTriggerContext) -> bool:
        return len(ctx.recent_actions) == 1 and ctx.recent_actions[0].title == "t"

    t = PredicateProactiveTrigger(
        trigger_id="act",
        body="offer",
        predicate=pred,
    )
    ctx = ProactiveTriggerContext(recent_actions=(a,))
    r = t.evaluate(ctx)
    assert r is not None


def test_from_slim_actions_sets_urls_and_recent_actions() -> None:
    a = SlimAction(title="p1", description="", canonical_url="https://x/a", index=0)
    b = SlimAction(title="p2", description="", canonical_url="", index=1)
    ctx = ProactiveTriggerContext.from_slim_actions(
        [a, b],
        product_id="prod",
        session_id="s",
        action_count=2,
    )
    assert ctx.recent_actions == (a, b)
    assert ctx.canonical_urls == ("https://x/a", None)


def test_from_actions_payloads_lookback_filters_old_batches() -> None:
    now = 1_000_000.0
    old = ActionsPayload(
        product_id="p",
        session_id="s",
        user_id=None,
        email=None,
        actions=[
            SlimAction(title="o", description="", canonical_url="https://old", index=0),
        ],
        count=1,
        forwarded_at=now - DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S - 10.0,
    )
    new = ActionsPayload(
        product_id="p",
        session_id="s",
        user_id=None,
        email=None,
        actions=[
            SlimAction(title="n", description="", canonical_url="https://new", index=0),
        ],
        count=1,
        forwarded_at=now,
    )
    ctx = ProactiveTriggerContext.from_actions_payloads(
        [old, new],
        now=now,
        session_id="s",
        product_id="p",
    )
    assert len(ctx.recent_actions) == 1
    assert ctx.canonical_urls == ("https://new",)


def test_from_actions_payloads_max_actions_trims_oldest() -> None:
    now = 2_000_000.0
    batch = ActionsPayload(
        product_id="p",
        session_id="s",
        user_id=None,
        email=None,
        actions=[
            SlimAction(title="a", description="", canonical_url="/1", index=0),
            SlimAction(title="b", description="", canonical_url="/2", index=1),
            SlimAction(title="c", description="", canonical_url="/3", index=2),
        ],
        count=3,
        forwarded_at=now,
    )
    ctx = ProactiveTriggerContext.from_actions_payloads(
        [batch],
        now=now,
        max_actions=2,
        lookback_seconds=None,
        session_id="s",
        product_id="p",
    )
    assert len(ctx.recent_actions) == 2
    assert [a.canonical_url for a in ctx.recent_actions] == ["/2", "/3"]


def test_from_actions_payloads_ping_pong_matches_default_registry() -> None:
    now = 3_000_000.0
    batch = ActionsPayload(
        product_id="p",
        session_id="s",
        user_id=None,
        email=None,
        actions=[
            SlimAction(
                title="p1", description="", canonical_url="https://app/a", index=0
            ),
            SlimAction(
                title="p2", description="", canonical_url="https://app/b", index=1
            ),
            SlimAction(
                title="p3", description="", canonical_url="https://app/a", index=2
            ),
        ],
        count=3,
        forwarded_at=now,
    )
    ctx = ProactiveTriggerContext.from_actions_payloads(
        [batch],
        now=now,
        lookback_seconds=None,
        max_actions=None,
        session_id="s",
        product_id="p",
    )
    reg = default_proactive_trigger_registry()
    r = reg.evaluate_first(ctx)
    assert r is not None
    assert r.trigger_id == TRIGGER_ID_CANONICAL_URL_PING_PONG


def test_scope_strict_raises_when_product_id_missing() -> None:
    with pytest.raises(ValueError):
        ProactiveTriggerContext.from_slim_actions(
            [SlimAction(title="t", description="", canonical_url="/", index=0)],
            session_id="s",
            product_id="",
        )


def test_scope_lenient_allows_empty_product_id() -> None:
    ctx = ProactiveTriggerContext.from_slim_actions(
        [SlimAction(title="t", description="", canonical_url="/", index=0)],
        session_id="s",
        product_id="",
        scope_policy=ScopePolicy.LENIENT,
    )
    assert ctx.product_id == ""


def test_validate_scope_instance_method() -> None:
    ctx = ProactiveTriggerContext(product_id="p", session_id="s")
    ctx.validate_scope()


def test_proactive_scope_dataclass() -> None:
    s = ProactiveScope(product_id="p", session_id="sid", conversation_id="c1")
    assert s.has_chat_surface()


def test_default_context_constants_match_helpers() -> None:
    assert DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S == 120.0
    assert DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS == 50


def test_proactive_trigger_context_summary_fields() -> None:
    ctx = ProactiveTriggerContext(
        latest_summary_text="last",
        prior_session_summaries=("older",),
        context_extra={"tier": "pro"},
    )
    assert ctx.latest_summary_text == "last"
    assert ctx.prior_session_summaries == ("older",)
    assert ctx.context_extra["tier"] == "pro"
