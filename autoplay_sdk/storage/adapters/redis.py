"""autoplay_sdk.storage.adapters.redis — Redis storage adapter (primary).

The default, read+write adapter. Owns a lazily-created ``redis.asyncio`` client
(mirrors ``RedisSessionStateStore`` / ``RedisEventBuffer``) and degrades
gracefully: on any Redis error reads return ``None`` and writes log a warning
rather than raising, so the host application never crashes on a Redis blip.

Session snapshots are written with ``SET ... NX`` (write-once) so a duplicate
session-end (e.g. a retry) can never overwrite a frozen snapshot.

Requires the ``redis`` extra::

    pip install "autoplay-sdk[redis]"
"""

from __future__ import annotations

import json
import logging
from typing import Any

from autoplay_sdk.storage.base import AutoplayStorageAdapter
from autoplay_sdk.storage.keys import session_key, user_state_key

logger = logging.getLogger(__name__)


class RedisStorageAdapter(AutoplayStorageAdapter):
    """Redis-backed adapter; the primary (readable) storage tier.

    Args:
        redis_url: ``redis://...`` connection URL.
        ttl_s: Optional TTL in seconds applied to both user state and session
            snapshots. Defaults to ``None`` (no expiry — state and snapshots are
            permanent, per spec).
    """

    def __init__(self, redis_url: str, *, ttl_s: int | None = None) -> None:
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "RedisStorageAdapter requires the redis package. "
                'Install it with: pip install "autoplay-sdk[redis]"'
            ) from exc
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._ttl_s = ttl_s

    async def save_user_state(
        self, product_id: str, user_id: str, state: dict[str, Any]
    ) -> None:
        key = user_state_key(product_id, user_id)
        try:
            await self._redis.set(key, json.dumps(state), ex=self._ttl_s)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RedisStorageAdapter: save_user_state failed product=%s user=%s: %s",
                product_id,
                user_id,
                exc,
            )

    async def get_user_state(
        self, product_id: str, user_id: str
    ) -> dict[str, Any] | None:
        key = user_state_key(product_id, user_id)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RedisStorageAdapter: get_user_state failed product=%s user=%s: %s",
                product_id,
                user_id,
                exc,
            )
            return None
        return self._loads(raw)

    async def save_session_snapshot(
        self,
        product_id: str,
        user_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        key = session_key(product_id, user_id, session_id)
        try:
            # nx=True -> write-once; a retried session-end never overwrites.
            await self._redis.set(key, json.dumps(snapshot), nx=True, ex=self._ttl_s)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RedisStorageAdapter: save_session_snapshot failed product=%s "
                "user=%s session=%s: %s",
                product_id,
                user_id,
                session_id,
                exc,
            )

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        key = session_key(product_id, user_id, session_id)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RedisStorageAdapter: get_session_snapshot failed product=%s "
                "user=%s session=%s: %s",
                product_id,
                user_id,
                session_id,
                exc,
            )
            return None
        return self._loads(raw)

    @staticmethod
    def _loads(raw: Any) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("RedisStorageAdapter: corrupt JSON in redis: %s", exc)
            return None
        return data if isinstance(data, dict) else None


__all__ = ["RedisStorageAdapter"]
