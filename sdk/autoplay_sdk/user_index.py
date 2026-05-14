"""autoplay_sdk.user_index — user-keyed session index for chatbot integrations.

`ContextStore` is keyed by session_id, while chatbot backends are often keyed by
user_id. `UserSessionIndex` bridges that gap by tracking recent
`user_id -> [(session_id, product_id, last_seen)]` links and exposing helper
methods to aggregate context across sessions.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from autoplay_sdk.context_store import AsyncContextStore, ContextStore
from autoplay_sdk.models import ActionsPayload

ContextStoreLike = ContextStore | AsyncContextStore


@dataclass(frozen=True)
class SessionRef:
    """User-linked session metadata stored in `UserSessionIndex`."""

    session_id: str
    product_id: str | None
    last_seen_at: float


class UserSessionIndex:
    """Tracks recent sessions per user and joins them into aggregate activity."""

    def __init__(
        self,
        context_store: ContextStoreLike,
        *,
        lookback_seconds: float = 300.0,
        max_sessions_per_user: int = 20,
    ) -> None:
        if lookback_seconds <= 0:
            raise ValueError("lookback_seconds must be > 0")
        if max_sessions_per_user < 1:
            raise ValueError("max_sessions_per_user must be >= 1")
        self._context_store = context_store
        self._lookback_seconds = lookback_seconds
        self._max_sessions_per_user = max_sessions_per_user
        self._lock = threading.Lock()
        self._user_sessions: dict[str, list[SessionRef]] = {}
        self._user_emails: dict[str, str] = {}

    def add(self, payload: ActionsPayload) -> None:
        """Index one actions payload by user/session."""
        user_id = (payload.user_id or "").strip()
        session_id = (payload.session_id or "").strip()
        if not user_id or not session_id:
            return
        now = payload.forwarded_at or time.time()
        with self._lock:
            if payload.email:
                self._user_emails[user_id] = payload.email
            bucket = self._user_sessions.get(user_id, [])
            bucket = [
                ref
                for ref in bucket
                if ref.session_id != session_id
                and now - ref.last_seen_at <= self._lookback_seconds
            ]
            bucket.append(
                SessionRef(
                    session_id=session_id,
                    product_id=(payload.product_id or None),
                    last_seen_at=now,
                )
            )
            bucket.sort(key=lambda ref: ref.last_seen_at, reverse=True)
            self._user_sessions[user_id] = bucket[: self._max_sessions_per_user]

    async def add_async(self, payload: ActionsPayload) -> None:
        """Async callback alias for `AsyncConnectorClient.on_actions`."""
        self.add(payload)

    def get_recent_sessions(self, user_id: str) -> list[SessionRef]:
        """Return recent sessions for a user, newest first."""
        now = time.time()
        with self._lock:
            bucket = self._user_sessions.get(user_id, [])
            bucket = [
                ref
                for ref in bucket
                if now - ref.last_seen_at <= self._lookback_seconds
            ]
            self._user_sessions[user_id] = bucket
            return list(bucket)

    def get_email(self, user_id: str) -> str | None:
        """Return last known email for a user (if captured)."""
        with self._lock:
            return self._user_emails.get(user_id)

    def get_user_activity(self, user_id: str) -> str:
        """Join context from recent sessions into one activity block."""
        blocks: list[str] = []
        for ref in self.get_recent_sessions(user_id):
            text = self._context_store.get(ref.session_id, product_id=ref.product_id)
            if not text:
                continue
            blocks.append(
                f"Session {ref.session_id} ({ref.product_id or 'no-product-id'}):\n{text}"
            )
        return "\n\n".join(blocks)

    def reset_user(self, user_id: str) -> None:
        """Drop all indexed sessions and cached email for one user."""
        with self._lock:
            self._user_sessions.pop(user_id, None)
            self._user_emails.pop(user_id, None)


__all__ = ["SessionRef", "UserSessionIndex"]
