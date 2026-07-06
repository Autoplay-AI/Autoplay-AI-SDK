"""autoplay_sdk.storage.lifecycle — session start / end orchestration.

Self-contained helpers that drive the cross-session loop on top of any
:class:`AutoplayStorageAdapter` (a single adapter or a ``StorageManager``):

- ``on_session_start`` loads (or initializes) the user's state and, for
  returning users, fetches the onboarding (session 1) snapshot for context.
- ``on_session_end`` freezes the session snapshot (write-once), refreshes the
  mutable user state, and appends the session to the index.
- ``build_agent_context`` projects state (+ onboarding snapshot) into the
  ``context_extra`` dict the proactive trigger engine consumes.

The SDK never calls an LLM. ``on_session_end`` resolves the onboarding summary
from an injected ``summarizer`` callable (or a pre-computed ``summary``); when
neither is supplied the summary is left unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from autoplay_sdk.storage.base import AutoplayStorageAdapter
from autoplay_sdk.user_adoption_state import (
    Mastery,
    SessionIndexEntry,
    SessionSnapshot,
    UserAdoptionState,
)

logger = logging.getLogger(__name__)

# Produces the onboarding-summary string from a freshly captured snapshot.
Summarizer = Callable[[SessionSnapshot], Awaitable[str]]

_ONBOARDING_SESSION_NUMBER = 1


def init_user_state(
    user_id: str, *, metadata: dict[str, Any] | None = None
) -> UserAdoptionState:
    """Build a fresh adoption record for a brand-new user."""
    return UserAdoptionState(user_id=user_id, metadata=dict(metadata or {}))


def _load_or_init(raw: dict[str, Any] | None, user_id: str) -> UserAdoptionState:
    if raw:
        try:
            return UserAdoptionState.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 — corrupt snapshot must not crash
            logger.warning(
                "storage.lifecycle: corrupt user state for user=%s, "
                "re-initializing: %s",
                user_id,
                exc,
                extra={"event_type": "user_state_reinit"},
            )
    return init_user_state(user_id)


async def on_session_start(
    product_id: str,
    user_id: str,
    session_id: str,
    storage: AutoplayStorageAdapter,
) -> tuple[UserAdoptionState, SessionSnapshot | None]:
    """Open a session: load/create user state and fetch onboarding context.

    Returns ``(state, onboarding_session)`` where ``onboarding_session`` is the
    frozen session-1 snapshot for returning users (``None`` on the first
    session or when it cannot be loaded).
    """
    raw = await storage.get_user_state(product_id, user_id)
    state = _load_or_init(raw, user_id)
    state.set_current_session(session_id)
    await storage.save_user_state(product_id, user_id, state.to_dict())

    onboarding_session: SessionSnapshot | None = None
    if state.sessions_count > 0:
        onboarding_session = await _get_onboarding_session(
            product_id, user_id, state, storage
        )
    return state, onboarding_session


async def _get_onboarding_session(
    product_id: str,
    user_id: str,
    state: UserAdoptionState,
    storage: AutoplayStorageAdapter,
) -> SessionSnapshot | None:
    entry = next(
        (
            e
            for e in state.sessions_index
            if e.session_number == _ONBOARDING_SESSION_NUMBER
        ),
        None,
    )
    if entry is None:
        return None
    raw = await storage.get_session_snapshot(product_id, user_id, entry.session_id)
    if not raw:
        return None
    try:
        return SessionSnapshot.from_dict(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "storage.lifecycle: corrupt onboarding snapshot user=%s session=%s: %s",
            user_id,
            entry.session_id,
            exc,
        )
        return None


async def on_session_end(
    product_id: str,
    user_id: str,
    session_snapshot: SessionSnapshot,
    storage: AutoplayStorageAdapter,
    *,
    summarizer: Summarizer | None = None,
    summary: str | None = None,
) -> UserAdoptionState:
    """Close a session: freeze the snapshot and refresh the user state.

    Steps: (1) write the snapshot once (``SET NX`` at the adapter), (2) load the
    current user state, (3) resolve the onboarding summary via the injected
    ``summarizer``/``summary`` (the SDK never calls an LLM), (4) sync the
    cross-session fields from the snapshot, (5) append the session to the index,
    (6) persist. Returns the updated state.
    """
    # 1. Freeze the snapshot first (write-once; safe under session-end retries).
    await storage.save_session_snapshot(
        product_id, user_id, session_snapshot.session_id, session_snapshot.to_dict()
    )

    # 2. Load the current user state (or initialize defensively).
    raw = await storage.get_user_state(product_id, user_id)
    state = _load_or_init(raw, user_id)

    # 3. Resolve the summary without ever calling an LLM in the SDK.
    resolved_summary = summary
    if resolved_summary is None and summarizer is not None:
        try:
            resolved_summary = await summarizer(session_snapshot)
        except Exception as exc:  # noqa: BLE001 — a summary failure must not lose the session
            logger.warning(
                "storage.lifecycle: summarizer failed user=%s session=%s: %s",
                user_id,
                session_snapshot.session_id,
                exc,
                extra={"event_type": "onboarding_summary_failed"},
            )
            resolved_summary = None

    # 4. Sync cross-session fields from the (authoritative) snapshot.
    state.journey_state = session_snapshot.journey_state
    state.mastery = Mastery(
        rating=session_snapshot.mastery.rating,
        level=session_snapshot.mastery.level,
        description=session_snapshot.mastery.description,
    )
    state.onboarding.completion_rate = session_snapshot.completion_rate
    if resolved_summary is not None:
        state.onboarding.summary = resolved_summary
    if session_snapshot.reached_onboarding_complete:
        state.onboarding.mark_onboarding_complete(now=session_snapshot.captured_at)
    state.record_discovered_features(session_snapshot.discovered_features)

    # 5. Append the lightweight session envelope (bounded index, true count).
    state.record_session(
        SessionIndexEntry(
            session_id=session_snapshot.session_id,
            session_number=session_snapshot.session_number,
            started_at=session_snapshot.started_at,
            captured_at=session_snapshot.captured_at,
        )
    )

    # 6. Persist the refreshed state.
    await storage.save_user_state(product_id, user_id, state.to_dict())
    return state


def build_agent_context(
    state: UserAdoptionState,
    onboarding_session: SessionSnapshot | None = None,
) -> dict[str, Any]:
    """Project state (+ onboarding snapshot) into ``ProactiveTriggerContext.context_extra``.

    Returns the small, agent-facing dict — not the raw documents.
    """
    ctx: dict[str, Any] = {
        "user_journey_state": state.journey_state.value,
        "user_mastery_level": state.mastery.level.value,
        "user_mastery_rating": state.mastery.rating,
        "session_count": state.sessions_count,
        "is_returning_user": state.sessions_count > 1,
    }
    if state.onboarding.summary:
        ctx["onboarding_summary"] = state.onboarding.summary
    if onboarding_session is not None:
        ctx["onboarding_session_in_progress_workflows"] = list(
            onboarding_session.in_progress_workflow_ids
        )
        ctx["onboarding_session_untouched_workflows"] = list(
            onboarding_session.untouched_workflow_ids
        )
    return ctx


__all__ = [
    "Summarizer",
    "init_user_state",
    "on_session_start",
    "on_session_end",
    "build_agent_context",
]
