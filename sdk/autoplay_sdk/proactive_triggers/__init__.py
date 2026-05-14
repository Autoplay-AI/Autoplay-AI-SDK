"""Proactive trigger detection — context, results, registry, built-in triggers.

There are **two** supported approaches:

1. **SDK built-ins** — listed in :mod:`autoplay_sdk.proactive_triggers.builtin_catalog`
   (today ``canonical_url_ping_pong``; more ids ship with the SDK). Configure ordered
   triggers via the host product row (event connector: ``proactive_triggers.builtins``)
   or call :func:`registry_from_builtin_specs` / :func:`default_proactive_trigger_registry`.

2. **Your own triggers** — implement :class:`ProactiveTrigger` or use
   :class:`PredicateProactiveTrigger`, compose :class:`ProactiveTriggerRegistry` in **code**.
   Host JSON cannot load arbitrary Python predicates.

Use :meth:`ProactiveTriggerRegistry.evaluate_first` to pick one proactive message; pair
:class:`ProactiveTriggerResult` with channel helpers (e.g. Intercom ``quick_reply``).

Cooldown and deduplication per ``(conversation_id, trigger_id)`` stay in your application.
"""

from __future__ import annotations

from autoplay_sdk.proactive_triggers.context_source import (
    RecentActionsPayloadSource,
    build_proactive_context_from_payloads,
)
from autoplay_sdk.proactive_triggers.builtin_catalog import (
    BUILTIN_TRIGGER_CATALOG,
    BuiltinTriggerCatalogEntry,
    ResolvedBuiltinTriggerSpec,
    list_builtin_trigger_catalog,
    registry_from_builtin_specs,
    resolve_builtin_specs,
)
from autoplay_sdk.proactive_triggers.defaults import (
    PROACTIVE_TRIGGER_IDS,
    ProactiveTriggerIds,
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
    TRIGGER_ID_SECTION_PLAYBOOK_MATCH,
    TRIGGER_ID_USER_PAGE_DWELL,
    get_proactive_trigger_ids,
)
from autoplay_sdk.proactive_triggers.judge import (
    LlmJudgeResult,
    META_JUDGE_REASONING,
    META_JUDGE_SCHEMA_VERSION,
    META_PROACTIVE_INTENT,
    META_PROACTIVE_VALID_TIMING,
    META_TRIGGERING_TYPE,
    TRIGGERING_TYPE_INSTANT,
    TRIGGERING_TYPE_LLM_JUDGE,
    attach_triggering_type,
    judge_result_to_proactive_trigger_result,
    parse_llm_judge_json,
    partition_results_by_triggering_type,
    should_deliver_after_judge,
    validate_or_truncate_proactive_body,
)
from autoplay_sdk.proactive_triggers.entity import ProactiveTriggerEntity
from autoplay_sdk.proactive_triggers.pending_tour_offer import (
    PendingTourOffer,
    pending_offer_to_json,
    resolve_pending_redis_value,
)
from autoplay_sdk.proactive_triggers.predicate_trigger import PredicateProactiveTrigger
from autoplay_sdk.proactive_triggers.proactive_intercom_config import (
    TOUR_OFFER_QUICK_REPLY_BODY,
    ProactiveIntercomMessageRow,
    effective_tour_flow_id_for_row,
    match_message_row_by_inbound_text,
    parse_proactive_intercom_messages,
    quick_reply_labels_from_messages_config,
    tour_offer_quick_reply_body,
)
from autoplay_sdk.proactive_triggers.registry import ProactiveTriggerRegistry
from autoplay_sdk.proactive_triggers.scope import (
    SCOPE_INVALID_EVENT,
    ProactiveScope,
    ScopePolicy,
    log_scope_violation,
)
from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S,
    DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS,
    PROACTIVE_BODY_MAX_CHARS,
    ProactiveTrigger,
    ProactiveTriggerContext,
    ProactiveTriggerResult,
    ProactiveTriggerTimings,
)


def __getattr__(name: str):
    """Lazy import for triggers so :mod:`intercom` can load :mod:`defaults` without a cycle."""
    if name == "CanonicalPingPongTrigger":
        from autoplay_sdk.proactive_triggers.triggers import CanonicalPingPongTrigger

        return CanonicalPingPongTrigger
    if name == "UserPageDwellTrigger":
        from autoplay_sdk.proactive_triggers.triggers import UserPageDwellTrigger

        return UserPageDwellTrigger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_proactive_trigger_registry() -> ProactiveTriggerRegistry:
    """Single default row from the built-in catalog (today: canonical URL ping-pong).

    Same catalog source as :func:`registry_from_builtin_specs`; use when host config does
    not set an explicit ``builtins`` list. Fills **id** / **name** / **description** from
    the catalog entry (required by :func:`registry_from_builtin_specs`).
    """
    entry = BUILTIN_TRIGGER_CATALOG[TRIGGER_ID_CANONICAL_URL_PING_PONG]
    return registry_from_builtin_specs(
        [
            {
                "id": entry.id,
                "name": entry.name,
                "description": entry.description,
            }
        ],
    )


__all__ = [
    "PendingTourOffer",
    "ProactiveIntercomMessageRow",
    "BUILTIN_TRIGGER_CATALOG",
    "BuiltinTriggerCatalogEntry",
    "RecentActionsPayloadSource",
    "build_proactive_context_from_payloads",
    "CanonicalPingPongTrigger",
    "UserPageDwellTrigger",
    "DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S",
    "DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS",
    "LlmJudgeResult",
    "META_JUDGE_REASONING",
    "META_JUDGE_SCHEMA_VERSION",
    "META_PROACTIVE_INTENT",
    "META_PROACTIVE_VALID_TIMING",
    "META_TRIGGERING_TYPE",
    "PROACTIVE_BODY_MAX_CHARS",
    "PredicateProactiveTrigger",
    "PROACTIVE_TRIGGER_IDS",
    "ResolvedBuiltinTriggerSpec",
    "ProactiveScope",
    "ProactiveTrigger",
    "ProactiveTriggerContext",
    "ProactiveTriggerEntity",
    "ProactiveTriggerIds",
    "ProactiveTriggerRegistry",
    "ProactiveTriggerResult",
    "ProactiveTriggerTimings",
    "SCOPE_INVALID_EVENT",
    "ScopePolicy",
    "TRIGGERING_TYPE_INSTANT",
    "TRIGGERING_TYPE_LLM_JUDGE",
    "TRIGGER_ID_USER_PAGE_DWELL",
    "TRIGGER_ID_CANONICAL_URL_PING_PONG",
    "TRIGGER_ID_SECTION_PLAYBOOK_MATCH",
    "attach_triggering_type",
    "default_proactive_trigger_registry",
    "get_proactive_trigger_ids",
    "judge_result_to_proactive_trigger_result",
    "list_builtin_trigger_catalog",
    "log_scope_violation",
    "parse_llm_judge_json",
    "partition_results_by_triggering_type",
    "TOUR_OFFER_QUICK_REPLY_BODY",
    "effective_tour_flow_id_for_row",
    "match_message_row_by_inbound_text",
    "parse_proactive_intercom_messages",
    "pending_offer_to_json",
    "quick_reply_labels_from_messages_config",
    "tour_offer_quick_reply_body",
    "resolve_pending_redis_value",
    "registry_from_builtin_specs",
    "resolve_builtin_specs",
    "should_deliver_after_judge",
    "validate_or_truncate_proactive_body",
]
