"""autoplay_sdk.storage.base — the pluggable storage adapter interface.

Implement this protocol to persist Autoplay user state and session snapshots to
any destination (Redis, Postgres, a data warehouse, an analytics sink, ...).
Modelled on :class:`autoplay_sdk.buffer.BufferBackend`: a
``@runtime_checkable`` ``Protocol`` rather than an ABC, so any object with the
right async methods qualifies — no forced inheritance.

The wire boundary is plain JSON-serializable ``dict`` objects (the result of a
model's ``to_dict()``), not SDK dataclasses, so custom adapters stay decoupled
from the SDK's model classes. Typed conversion happens one layer up in
:mod:`autoplay_sdk.storage.lifecycle`.

Two storage tiers:

- **User state** (``save_user_state`` / ``get_user_state``) is mutable and
  overwritten each session.
- **Session snapshot** (``save_session_snapshot`` / ``get_session_snapshot``)
  is frozen and **write-once** — implementations MUST NOT overwrite an existing
  ``session_id`` (e.g. Redis ``SET ... NX``).

Write-only sinks (analytics destinations) implement the ``save_*`` methods and
return ``None`` from the ``get_*`` methods; reads are served by the primary
adapter (Redis).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AutoplayStorageAdapter(Protocol):
    """Async persistence backend for user state + session snapshots."""

    async def save_user_state(
        self, product_id: str, user_id: str, state: dict[str, Any]
    ) -> None:
        """Persist (overwrite) the mutable user-level state document."""
        ...

    async def get_user_state(
        self, product_id: str, user_id: str
    ) -> dict[str, Any] | None:
        """Load user-level state, or ``None`` if not found / not supported."""
        ...

    async def save_session_snapshot(
        self,
        product_id: str,
        user_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        """Persist a frozen session snapshot.

        Must be write-once: do not overwrite if ``session_id`` already exists.
        """
        ...

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        """Load a specific session snapshot, or ``None`` if not found."""
        ...


__all__ = ["AutoplayStorageAdapter"]
