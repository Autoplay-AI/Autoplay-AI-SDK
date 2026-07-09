"""autoplay_sdk.storage.adapters.memory — in-process storage adapter.

For tests and local development only; state lives in process memory and is lost
on restart and not shared across processes. Mirrors the naming of
``InMemorySessionStateStore`` / ``InMemoryConversationLinkStore``.

Snapshots are write-once: a second ``save_session_snapshot`` for an existing
``session_id`` is a no-op (the ``SET NX`` semantics the real adapters enforce).
"""

from __future__ import annotations

import copy
from typing import Any

from autoplay_sdk.storage.base import AutoplayStorageAdapter


class InMemoryStorageAdapter(AutoplayStorageAdapter):
    """Dict-backed adapter for tests / dev."""

    def __init__(self) -> None:
        self._user_state: dict[tuple[str, str], dict[str, Any]] = {}
        self._snapshots: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def save_user_state(
        self, product_id: str, user_id: str, state: dict[str, Any]
    ) -> None:
        self._user_state[(product_id, user_id)] = copy.deepcopy(state)

    async def get_user_state(
        self, product_id: str, user_id: str
    ) -> dict[str, Any] | None:
        found = self._user_state.get((product_id, user_id))
        return copy.deepcopy(found) if found is not None else None

    async def save_session_snapshot(
        self,
        product_id: str,
        user_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        key = (product_id, user_id, session_id)
        # Write-once: never overwrite an existing frozen snapshot.
        if key in self._snapshots:
            return
        self._snapshots[key] = copy.deepcopy(snapshot)

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        found = self._snapshots.get((product_id, user_id, session_id))
        return copy.deepcopy(found) if found is not None else None


__all__ = ["InMemoryStorageAdapter"]
