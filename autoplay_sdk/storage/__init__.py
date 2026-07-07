"""autoplay_sdk.storage — cross-session user & session state persistence.

A pluggable storage subsystem for the per-user adoption record
(:class:`autoplay_sdk.user_adoption_state.UserAdoptionState`) and frozen
per-session snapshots (:class:`autoplay_sdk.user_adoption_state.SessionSnapshot`).

Layers:

- :class:`AutoplayStorageAdapter` — the interface (a ``Protocol``) customers
  implement to target any destination.
- :class:`StorageManager` — fans writes out to many adapters and reads from the
  primary (first) one.
- :class:`RedisStorageAdapter` / :class:`InMemoryStorageAdapter` — built-in
  adapters. Write-only analytics sinks live in
  ``autoplay_sdk.storage.adapters.{amplitude,posthog}`` (deep-import; needs the
  ``autoplay-sdk[analytics]`` extra).
- :mod:`autoplay_sdk.storage.lifecycle` — ``on_session_start`` /
  ``on_session_end`` / ``build_agent_context`` orchestration helpers.

The SDK never calls an LLM: the onboarding summary is supplied via an injected
``summarizer`` callable on ``on_session_end``.
"""

from __future__ import annotations

from autoplay_sdk.storage.adapters.memory import InMemoryStorageAdapter
from autoplay_sdk.storage.adapters.redis import RedisStorageAdapter
from autoplay_sdk.storage.base import AutoplayStorageAdapter
from autoplay_sdk.storage.keys import session_key, user_state_key
from autoplay_sdk.storage.lifecycle import (
    build_agent_context,
    init_user_state,
    on_session_end,
    on_session_start,
)
from autoplay_sdk.storage.manager import StorageManager

__all__ = [
    "AutoplayStorageAdapter",
    "StorageManager",
    "RedisStorageAdapter",
    "InMemoryStorageAdapter",
    "user_state_key",
    "session_key",
    "init_user_state",
    "on_session_start",
    "on_session_end",
    "build_agent_context",
]
