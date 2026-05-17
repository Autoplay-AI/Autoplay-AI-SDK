from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

# Host-defined surface id (e.g. "intercom", "slack") — not an Intercom API symbol.
ProactiveSurfaceId = NewType("ProactiveSurfaceId", str)

# Version segment so key layout can evolve without colliding with old TTLs.
_KEY_VERSION = "v1"


def proactive_key_namespace() -> str:
    """Logical namespace segment; host prepends e.g. ``connector:proactive:``."""
    return _KEY_VERSION


def _norm(s: str) -> str:
    return (s or "").strip()


@dataclass(frozen=True, slots=True)
class ProactiveResilienceKeySpace:
    """Pure key suffix builders for Redis (or other) storage.

    Hosts should prefix with a deployment namespace, e.g. ``connector:proactive:``.
    """

    surface: str
    product_id: str

    def _base(self) -> str:
        return f"{_KEY_VERSION}:{_norm(self.surface)}:{_norm(self.product_id)}"

    def circuit_open_key(self) -> str:
        return f"{self._base()}:circuit_open"

    def fail_streak_key(self) -> str:
        return f"{self._base()}:fail_streak"

    def min_interval_key(self, session_id: str) -> str:
        return f"{self._base()}:min_interval:{_norm(session_id)}"

    def attempts_per_minute_key(self, window_start_epoch_min: int) -> str:
        return f"{self._base()}:attempts_min:{window_start_epoch_min}"

    def per_session_hour_key(self, session_id: str, hour_start_epoch: int) -> str:
        return f"{self._base()}:sess_hour:{_norm(session_id)}:{hour_start_epoch}"

    def per_user_day_key(self, user_bucket: str, day_utc: str) -> str:
        return f"{self._base()}:user_day:{_norm(user_bucket)}:{_norm(day_utc)}"


def proactive_key_suffixes(
    *, surface: str, product_id: str, session_id: str
) -> dict[str, str]:
    """Convenience map of human-readable key roles to full suffix strings."""
    ks = ProactiveResilienceKeySpace(surface=surface, product_id=product_id)
    return {
        "circuit_open": ks.circuit_open_key(),
        "fail_streak": ks.fail_streak_key(),
        "min_interval": ks.min_interval_key(session_id),
    }
