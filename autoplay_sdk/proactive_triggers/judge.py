"""LLM judge contract, metadata keys, and pure helpers for proactive delivery.

Hosts that run their own LLM can parse JSON into :class:`LlmJudgeResult` and map to
:class:`~autoplay_sdk.proactive_triggers.types.ProactiveTriggerResult` using the helpers
here without importing the event connector.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Literal

from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_INTERACTION_TIMEOUT_S,
    PROACTIVE_BODY_MAX_CHARS,
    ProactiveTriggerResult,
)

# --- Metadata keys (stable for analytics / logs) ---

META_TRIGGERING_TYPE = "triggering_type"
META_PROACTIVE_VALID_TIMING = "proactive_valid_timing"
META_JUDGE_REASONING = "judge_reasoning"
META_PROACTIVE_INTENT = "proactive_intent"
META_JUDGE_SCHEMA_VERSION = "judge_schema_version"

# --- Triggering type (per built-in; echoed on each ProactiveTriggerResult) ---

TRIGGERING_TYPE_INSTANT = "instant_trigger"
TRIGGERING_TYPE_LLM_JUDGE = "llm_judge_validation"

ProactiveIntent = Literal["assist", "coaching_tip", "none"]


@dataclass(frozen=True)
class LlmJudgeResult:
    """Structured output from the proactive LLM judge (portable across hosts).

    **schema_version** — bump when adding/removing JSON fields for migration notes.
    """

    schema_version: str = "1.0"
    send: bool = False
    proactive_valid_timing: bool = False
    short_user_message: str = ""
    reasoning: str = ""
    proactive_intent: str = "none"

    def to_metadata_fragment(self) -> dict[str, Any]:
        """Fields suitable for merging onto :class:`ProactiveTriggerResult.metadata`."""
        return {
            META_PROACTIVE_VALID_TIMING: self.proactive_valid_timing,
            META_JUDGE_REASONING: self.reasoning,
            META_PROACTIVE_INTENT: self.proactive_intent,
            META_JUDGE_SCHEMA_VERSION: self.schema_version,
        }


def validate_or_truncate_proactive_body(
    text: str, *, max_chars: int = PROACTIVE_BODY_MAX_CHARS
) -> str:
    """Return user-visible proactive text capped at **max_chars** (Unicode-safe slice)."""
    if not text:
        return ""
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip()


def partition_results_by_triggering_type(
    results: list[ProactiveTriggerResult],
) -> tuple[list[ProactiveTriggerResult], list[ProactiveTriggerResult]]:
    """Split registry hits into **instant** vs **LLM-judge-gated** paths."""
    instant: list[ProactiveTriggerResult] = []
    gated: list[ProactiveTriggerResult] = []
    for r in results:
        tt = (r.metadata or {}).get(META_TRIGGERING_TYPE, TRIGGERING_TYPE_LLM_JUDGE)
        if tt == TRIGGERING_TYPE_INSTANT:
            instant.append(r)
        else:
            gated.append(r)
    return instant, gated


def should_deliver_after_judge(judge: LlmJudgeResult) -> bool:
    """True when the judge authorizes sending non-empty proactive copy."""
    if not judge.send or not judge.proactive_valid_timing:
        return False
    return bool(validate_or_truncate_proactive_body(judge.short_user_message))


def judge_result_to_proactive_trigger_result(
    judge: LlmJudgeResult,
    candidates: list[ProactiveTriggerResult],
    *,
    primary_trigger_id: str | None = None,
) -> ProactiveTriggerResult | None:
    """Merge judge output with deterministic candidates into one delivery result.

    Uses **primary_trigger_id** when set; else the first candidate's ``trigger_id``;
    if there are no candidates, uses ``"llm_judge"``.
    """
    if not should_deliver_after_judge(judge):
        return None
    tid = primary_trigger_id or (
        candidates[0].trigger_id if candidates else "llm_judge"
    )
    body = validate_or_truncate_proactive_body(judge.short_user_message)
    base_meta: dict[str, Any] = {}
    for c in candidates:
        for k, v in (c.metadata or {}).items():
            base_meta.setdefault(k, v)
    merged_md = {**base_meta, **judge.to_metadata_fragment()}
    # Winning trigger id for dedupe / analytics
    first = candidates[0] if candidates else None
    return ProactiveTriggerResult(
        trigger_id=tid,
        body=body,
        reply_option_labels=first.reply_option_labels if first else (),
        metadata=merged_md,
        interaction_timeout_s=first.interaction_timeout_s
        if first
        else DEFAULT_INTERACTION_TIMEOUT_S,
        cooldown_s=first.cooldown_s if first else DEFAULT_COOLDOWN_S,
    )


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_JSON_FENCE_END = re.compile(r"```\s*$")


def parse_llm_judge_json(raw: str) -> LlmJudgeResult:
    """Parse assistant text into :class:`LlmJudgeResult` (tolerates markdown fences)."""
    s = (raw or "").strip()
    if not s:
        return LlmJudgeResult()
    s = _JSON_FENCE.sub("", s)
    s = _JSON_FENCE_END.sub("", s).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return LlmJudgeResult(reasoning="invalid_json_from_model")
    if not isinstance(data, dict):
        return LlmJudgeResult(reasoning="judge_payload_not_object")

    def _bool(key: str, default: bool = False) -> bool:
        v = data.get(key, default)
        if isinstance(v, bool):
            return v
        return default

    def _str(key: str, default: str = "") -> str:
        v = data.get(key, default)
        if v is None:
            return default
        return str(v).strip()

    intent = _str("proactive_intent", "none")
    if intent not in ("assist", "coaching_tip", "none"):
        intent = "none"

    return LlmJudgeResult(
        schema_version=_str("schema_version", "1.0") or "1.0",
        send=_bool("send", False),
        proactive_valid_timing=_bool("proactive_valid_timing", False),
        short_user_message=_str("short_user_message", "")
        or _str("what_to_send", "")
        or _str("body", ""),
        reasoning=_str("reasoning", ""),
        proactive_intent=intent,
    )


def attach_triggering_type(
    result: ProactiveTriggerResult,
    triggering_type: str,
) -> ProactiveTriggerResult:
    """Return a copy of **result** with :data:`META_TRIGGERING_TYPE` set."""
    md = dict(result.metadata or {})
    md[META_TRIGGERING_TYPE] = triggering_type
    return replace(result, metadata=md)
