"""Built-in storage adapters.

``InMemoryStorageAdapter`` and ``RedisStorageAdapter`` are exported here. The
write-only analytics sinks (``AmplitudeStorageAdapter`` / ``PostHogStorageAdapter``)
are intentionally NOT re-exported — import them explicitly from their modules
(``autoplay_sdk.storage.adapters.amplitude`` / ``.posthog``) and install the
``autoplay-sdk[analytics]`` extra — so the common import path stays lean.
"""

from __future__ import annotations

from autoplay_sdk.storage.adapters.memory import InMemoryStorageAdapter
from autoplay_sdk.storage.adapters.redis import RedisStorageAdapter

__all__ = ["InMemoryStorageAdapter", "RedisStorageAdapter"]
