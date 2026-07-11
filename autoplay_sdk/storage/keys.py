"""Redis key builders for the user / session storage subsystem.

Keys are product-scoped so a single Redis instance can back many products
(mirrors the multi-tenant convention used elsewhere in the connector).

    autoplay:user:{product_id}:{user_id}:state                 # mutable user state
    autoplay:user:{product_id}:{user_id}:session:{session_id}  # frozen snapshot
"""

from __future__ import annotations

_USER_STATE_KEY = "autoplay:user:{product_id}:{user_id}:state"
_SESSION_KEY = "autoplay:user:{product_id}:{user_id}:session:{session_id}"


def user_state_key(product_id: str, user_id: str) -> str:
    """Return the Redis key for a user's mutable state document."""
    return _USER_STATE_KEY.format(product_id=product_id, user_id=user_id)


def session_key(product_id: str, user_id: str, session_id: str) -> str:
    """Return the Redis key for a user's frozen session snapshot."""
    return _SESSION_KEY.format(
        product_id=product_id, user_id=user_id, session_id=session_id
    )


__all__ = ["user_state_key", "session_key"]
