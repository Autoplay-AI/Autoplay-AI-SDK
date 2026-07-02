"""autoplay_sdk.storage.manager — fan-out across multiple storage adapters.

Writes go to every registered adapter; a failure in one (e.g. an analytics
sink being down) is logged and never blocks the others. Reads return the first
adapter that produces a result — Redis is the primary and MUST be listed first,
since the write-only sinks always return ``None`` from their ``get_*`` methods.

The manager itself satisfies :class:`AutoplayStorageAdapter`, so it composes
anywhere a single adapter is expected (including inside another manager).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from autoplay_sdk.storage.base import AutoplayStorageAdapter

logger = logging.getLogger(__name__)


class StorageManager:
    """Fan-out writes / first-hit reads across an ordered list of adapters."""

    def __init__(self, adapters: Sequence[AutoplayStorageAdapter]) -> None:
        if not adapters:
            raise ValueError(
                "StorageManager requires at least one storage adapter. "
                "Put your primary (readable) adapter first, e.g. "
                "StorageManager([RedisStorageAdapter(redis_url=...)])."
            )
        self.adapters: list[AutoplayStorageAdapter] = list(adapters)

    async def save_user_state(
        self, product_id: str, user_id: str, state: dict[str, Any]
    ) -> None:
        for adapter in self.adapters:
            try:
                await adapter.save_user_state(product_id, user_id, state)
            except Exception as exc:  # noqa: BLE001 — one sink must not block others
                logger.warning(
                    "storage: save_user_state failed on %s product=%s user=%s: %s",
                    type(adapter).__name__,
                    product_id,
                    user_id,
                    exc,
                    extra={"event_type": "storage_adapter_write_failed"},
                )

    async def get_user_state(
        self, product_id: str, user_id: str
    ) -> dict[str, Any] | None:
        for adapter in self.adapters:
            try:
                result = await adapter.get_user_state(product_id, user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "storage: get_user_state failed on %s product=%s user=%s: %s",
                    type(adapter).__name__,
                    product_id,
                    user_id,
                    exc,
                    extra={"event_type": "storage_adapter_read_failed"},
                )
                continue
            if result is not None:
                return result
        return None

    async def save_session_snapshot(
        self,
        product_id: str,
        user_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        for adapter in self.adapters:
            try:
                await adapter.save_session_snapshot(
                    product_id, user_id, session_id, snapshot
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "storage: save_session_snapshot failed on %s product=%s "
                    "user=%s session=%s: %s",
                    type(adapter).__name__,
                    product_id,
                    user_id,
                    session_id,
                    exc,
                    extra={"event_type": "storage_adapter_write_failed"},
                )

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        for adapter in self.adapters:
            try:
                result = await adapter.get_session_snapshot(
                    product_id, user_id, session_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "storage: get_session_snapshot failed on %s product=%s "
                    "user=%s session=%s: %s",
                    type(adapter).__name__,
                    product_id,
                    user_id,
                    session_id,
                    exc,
                    extra={"event_type": "storage_adapter_read_failed"},
                )
                continue
            if result is not None:
                return result
        return None


__all__ = ["StorageManager"]
