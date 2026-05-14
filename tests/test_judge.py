"""Tests for proactive LLM judge helpers (SDK)."""

from __future__ import annotations

from autoplay_sdk.proactive_triggers.judge import (
    LlmJudgeResult,
    META_TRIGGERING_TYPE,
    TRIGGERING_TYPE_INSTANT,
    judge_result_to_proactive_trigger_result,
    parse_llm_judge_json,
    partition_results_by_triggering_type,
    should_deliver_after_judge,
    validate_or_truncate_proactive_body,
)
from autoplay_sdk.proactive_triggers.types import (
    PROACTIVE_BODY_MAX_CHARS,
    ProactiveTriggerResult,
)


def test_validate_or_truncate_proactive_body() -> None:
    assert validate_or_truncate_proactive_body("") == ""
    s = "a" * 200
    out = validate_or_truncate_proactive_body(s)
    assert len(out) == PROACTIVE_BODY_MAX_CHARS


def test_partition_results_by_triggering_type() -> None:
    a = ProactiveTriggerResult(
        trigger_id="a",
        body="x",
        metadata={META_TRIGGERING_TYPE: TRIGGERING_TYPE_INSTANT},
    )
    b = ProactiveTriggerResult(trigger_id="b", body="y", metadata={})
    ins, gated = partition_results_by_triggering_type([a, b])
    assert [x.trigger_id for x in ins] == ["a"]
    assert [x.trigger_id for x in gated] == ["b"]


def test_should_deliver_after_judge() -> None:
    assert not should_deliver_after_judge(LlmJudgeResult())
    assert not should_deliver_after_judge(
        LlmJudgeResult(send=True, proactive_valid_timing=False, short_user_message="hi")
    )
    assert should_deliver_after_judge(
        LlmJudgeResult(send=True, proactive_valid_timing=True, short_user_message="hi")
    )


def test_judge_result_to_proactive_trigger_result() -> None:
    cand = ProactiveTriggerResult(
        trigger_id="canonical_url_ping_pong",
        body="old",
        metadata={"k": 1},
        interaction_timeout_s=12.0,
        cooldown_s=20.0,
    )
    judge = LlmJudgeResult(
        send=True,
        proactive_valid_timing=True,
        short_user_message="New body",
        reasoning="ok",
        proactive_intent="assist",
    )
    out = judge_result_to_proactive_trigger_result(judge, [cand])
    assert out is not None
    assert out.trigger_id == "canonical_url_ping_pong"
    assert out.body == "New body"
    assert out.metadata.get("judge_reasoning") == "ok"


def test_parse_llm_judge_json_with_fence() -> None:
    raw = '```json\n{"send": true, "proactive_valid_timing": true, "short_user_message": "Hi", "reasoning": "r", "proactive_intent": "none"}\n```'
    j = parse_llm_judge_json(raw)
    assert j.send is True
    assert j.short_user_message == "Hi"


def test_parse_llm_judge_json_what_to_send_alias() -> None:
    j = parse_llm_judge_json(
        '{"send": true, "proactive_valid_timing": true, "what_to_send": "Alias body", "reasoning": ""}'
    )
    assert j.short_user_message == "Alias body"
