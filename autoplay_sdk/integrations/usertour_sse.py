"""Typed helpers for ``usertour_trigger`` events on the connector SSE stream."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class UsertourTriggerPayload(TypedDict, total=False):
    """Payload shape for :func:`stream_store.broadcast` user-tour / visual guidance."""

    type: str  # "usertour_trigger"
    product_id: str
    flow_id: str
    reason: str
    user_id: NotRequired[str]
    session_id: NotRequired[str]


USERTOUR_TRIGGER_EVENT_TYPE = "usertour_trigger"


def usertour_trigger_sse_minimal_dict(
    *,
    product_id: str,
    flow_id: str,
    session_id: str,
) -> dict[str, str]:
    """Exactly four keys for Autoplay popup tour triggers over SSE.

    The ``session_id`` **value** is the PostHog **session id** the connector
    associates with this user's activity for ``product_id`` (from webhook /
    identity store). Callers may fall back to distinct id when no session is
    linked yet.
    """
    return {
        "type": USERTOUR_TRIGGER_EVENT_TYPE,
        "product_id": product_id,
        "flow_id": flow_id,
        "session_id": (session_id or "").strip(),
    }


def usertour_trigger_sse_dict(
    *,
    product_id: str,
    flow_id: str,
    reason: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, str]:
    """Build a JSON-serializable dict for SSE fan-out (stable keys for browser clients)."""
    out: dict[str, str] = {
        "type": USERTOUR_TRIGGER_EVENT_TYPE,
        "product_id": product_id,
        "flow_id": flow_id,
        "reason": reason,
    }
    uid = (user_id or "").strip()
    if uid:
        out["user_id"] = uid
    sid = (session_id or "").strip()
    if sid:
        out["session_id"] = sid
    return out
