"""Shared types for proactive triggers (detection layer — any delivery surface)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Sequence, runtime_checkable

from autoplay_sdk.models import ActionsPayload, SlimAction
from autoplay_sdk.proactive_triggers.scope import (
    ScopePolicy,
    validate_proactive_scope_fields,
)

# Defaults shared with :class:`ProactiveTriggerResult` (single source of truth).
DEFAULT_INTERACTION_TIMEOUT_S = 10.0
DEFAULT_COOLDOWN_S = 30.0

# Max length for user-visible proactive copy (LLM judge + deterministic triggers).
PROACTIVE_BODY_MAX_CHARS = 150

# Defaults aligned with typical :class:`~autoplay_sdk.context_store.AsyncContextStore`
# connector deployments (2-minute window, 50 actions cap).
DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S = 120.0
DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS = 50


def _filter_payloads_by_lookback(
    payloads: list[ActionsPayload],
    *,
    lookback_seconds: float | None,
    now: float,
) -> list[ActionsPayload]:
    if lookback_seconds is None:
        return payloads
    if lookback_seconds <= 0:
        raise ValueError(
            f"lookback_seconds must be > 0 or None, got {lookback_seconds!r}"
        )
    cutoff = now - lookback_seconds
    return [p for p in payloads if p.forwarded_at >= cutoff]


def _trim_payloads_to_max_actions(
    payloads: list[ActionsPayload],
    max_actions: int | None,
) -> list[ActionsPayload]:
    """Keep only the most recent ``max_actions`` :class:`SlimAction` rows (batch-aware).

    Mirrors :meth:`autoplay_sdk.context_store._ContextStoreBase.get` — newest actions
    win; partial batches may be trimmed from the oldest side of that batch.
    """
    if max_actions is None or max_actions < 1:
        return payloads
    kept: list[ActionsPayload] = []
    total = 0
    for payload in reversed(payloads):
        remaining = max_actions - total
        if remaining <= 0:
            break
        actual_count = len(payload.actions)
        if actual_count <= remaining:
            kept.insert(0, payload)
            total += actual_count
        else:
            trimmed = replace(
                payload,
                actions=payload.actions[-remaining:],
                count=remaining,
            )
            kept.insert(0, trimmed)
            total += remaining
    return kept


@dataclass(frozen=True)
class ProactiveTriggerTimings:
    """Policy for how long a proactive offer may idle and how long before refire.

    **interaction_timeout_s** — if the user does not interact with the proactive
    UI within this window (definition is app-specific: tap, dismiss, message),
    hide the offer and return the session FSM to **thinking** via
    :meth:`autoplay_sdk.agent_states.AgentStateMachine.expire_proactive_to_thinking_if_idle`.

    **cooldown_s** — minimum spacing before the same trigger may fire again; apps
    typically store ``last_fired_at`` per ``(conversation_id, trigger_id)``.
    """

    interaction_timeout_s: float = DEFAULT_INTERACTION_TIMEOUT_S
    cooldown_s: float = DEFAULT_COOLDOWN_S


@dataclass(frozen=True)
class ProactiveTriggerContext:
    """Inputs available to proactive triggers.

    The **host application** fills this from SSE buffers, merged
    :class:`~autoplay_sdk.models.ActionsPayload`, session summary stores, etc.
    Defaults keep older call sites valid; extend fields in CHANGELOG when the
    shape changes incompatibly.

    **context_extra** is a mutable dict per instance (do not rely on immutability
    if you pass a shared reference from outside).
    """

    canonical_urls: Sequence[str | None] = ()
    session_id: str = ""
    conversation_id: str = ""
    action_count: int = 0
    product_id: str = ""
    recent_actions: tuple[SlimAction, ...] = ()
    latest_summary_text: str = ""
    prior_session_summaries: tuple[str, ...] = ()
    context_extra: dict[str, Any] = field(default_factory=dict)

    def validate_scope(
        self,
        *,
        policy: ScopePolicy = ScopePolicy.STRICT,
        require_conversation: bool = False,
    ) -> None:
        """Raise :exc:`ValueError` if scope identifiers violate ``policy`` (see :mod:`.scope`)."""
        validate_proactive_scope_fields(
            product_id=self.product_id,
            session_id=self.session_id,
            conversation_id=self.conversation_id,
            require_conversation=require_conversation,
            policy=policy,
        )

    @classmethod
    def from_slim_actions(
        cls,
        actions: Sequence[SlimAction],
        *,
        session_id: str = "",
        conversation_id: str = "",
        product_id: str = "",
        action_count: int = 0,
        latest_summary_text: str = "",
        prior_session_summaries: tuple[str, ...] = (),
        context_extra: dict[str, Any] | None = None,
        scope_policy: ScopePolicy = ScopePolicy.STRICT,
        require_conversation: bool = False,
    ) -> ProactiveTriggerContext:
        """Build context from an ordered sequence of actions (already windowed by the host).

        Sets ``canonical_urls`` from each action's ``canonical_url`` (empty → ``None``)
        and ``recent_actions`` to the same sequence as a tuple.

        Use :class:`ScopePolicy.STRICT` (default) so ``product_id`` and ``session_id``
        must be non-empty. Pass :class:`ScopePolicy.LENIENT` only for legacy paths.
        """
        validate_proactive_scope_fields(
            product_id=product_id,
            session_id=session_id,
            conversation_id=conversation_id,
            require_conversation=require_conversation,
            policy=scope_policy,
        )
        seq = tuple(actions)
        canonical_urls = tuple(a.canonical_url or None for a in seq)
        extra = dict(context_extra) if context_extra is not None else {}
        return cls(
            canonical_urls=canonical_urls,
            session_id=session_id,
            conversation_id=conversation_id,
            action_count=action_count,
            product_id=product_id,
            recent_actions=seq,
            latest_summary_text=latest_summary_text,
            prior_session_summaries=prior_session_summaries,
            context_extra=extra,
        )

    @classmethod
    def from_actions_payloads(
        cls,
        payloads: Sequence[ActionsPayload],
        *,
        lookback_seconds: float | None = DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S,
        max_actions: int | None = DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS,
        now: float | None = None,
        session_id: str = "",
        conversation_id: str = "",
        product_id: str = "",
        action_count: int = 0,
        latest_summary_text: str = "",
        prior_session_summaries: tuple[str, ...] = (),
        context_extra: dict[str, Any] | None = None,
        scope_policy: ScopePolicy = ScopePolicy.STRICT,
        require_conversation: bool = False,
    ) -> ProactiveTriggerContext:
        """Build context from connector/event batches: lookback + recent-action cap, then flatten.

        **lookback_seconds** — only payloads with ``forwarded_at >= now - lookback_seconds``.
        Pass ``None`` to disable time filtering.

        **max_actions** — keep at most this many most recent :class:`SlimAction` rows
        (after lookback). Pass ``None`` for no cap.

        **now** — defaults to :func:`time.time`; inject for deterministic tests.

        Chronological order matches payload order; actions within each payload stay in order.

        **scope_policy** — defaults to :class:`ScopePolicy.STRICT` (require ``product_id``
        and ``session_id``). Use :class:`ScopePolicy.LENIENT` when identifiers are optional.
        """
        if max_actions is not None and max_actions < 1:
            raise ValueError(f"max_actions must be >= 1 or None, got {max_actions!r}")

        tnow = time.time() if now is None else float(now)
        plist = list(payloads)
        plist = _filter_payloads_by_lookback(
            plist, lookback_seconds=lookback_seconds, now=tnow
        )
        plist = _trim_payloads_to_max_actions(plist, max_actions)

        flat: list[SlimAction] = []
        for p in plist:
            flat.extend(p.actions)

        return cls.from_slim_actions(
            flat,
            session_id=session_id,
            conversation_id=conversation_id,
            product_id=product_id,
            action_count=action_count,
            latest_summary_text=latest_summary_text,
            prior_session_summaries=prior_session_summaries,
            context_extra=context_extra,
            scope_policy=scope_policy,
            require_conversation=require_conversation,
        )


@dataclass(frozen=True)
class ProactiveTriggerResult:
    """What to send when a trigger fires (before channel-specific formatting).

    For Intercom ``quick_reply``, pair with
    :func:`autoplay_sdk.integrations.intercom.build_intercom_quick_reply_reply_payload`.

    **interaction_timeout_s** / **cooldown_s** default to :data:`DEFAULT_INTERACTION_TIMEOUT_S`
    and :data:`DEFAULT_COOLDOWN_S`; use :class:`ProactiveTriggerEntity` to attach custom
    timings without implementing them in every trigger.
    """

    trigger_id: str
    body: str
    reply_option_labels: Sequence[str] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    interaction_timeout_s: float = DEFAULT_INTERACTION_TIMEOUT_S
    cooldown_s: float = DEFAULT_COOLDOWN_S


@runtime_checkable
class ProactiveTrigger(Protocol):
    """Evaluate whether to surface proactive assistance for this context."""

    @property
    def trigger_id(self) -> str:
        """Stable id for logs, analytics, and per-trigger cooldown keys."""
        ...

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        """Return a result when this trigger fires; ``None`` otherwise."""
        ...
