"""Resolve Unkey Bearer token for ``GET /stream/{product_id}`` subscribers."""

from __future__ import annotations

import os


def resolve_connector_bearer_token(explicit: str) -> str:
    """Return the SSE Bearer token: explicit argument wins, else ``AUTOPLAY_APP_UNKEY_TOKEN``."""
    t = (explicit or "").strip()
    if t:
        return t
    return (os.getenv("AUTOPLAY_APP_UNKEY_TOKEN") or "").strip()
