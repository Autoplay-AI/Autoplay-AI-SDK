"""Optional session metadata for opt-in visual guidance after a scripted quick_reply."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingTourOffer:
    """Represents a pending \"Would you like me to show you?\" tour opt-in (host-persisted)."""

    flow_id: str


def pending_offer_to_json(flow_id: str) -> str:
    """Serialize :class:`PendingTourOffer` as Redis JSON (legacy ``\"1\"`` still accepted)."""
    fid = (flow_id or "").strip()
    return json.dumps({"flow_id": fid})


def resolve_pending_redis_value(raw: str | None, *, default_flow_id: str) -> str:
    """Map stored Redis value to a UserTour ``flow_id`` (legacy ``\"1\"`` → default)."""
    df = (default_flow_id or "").strip()
    if raw is None:
        return df
    s = str(raw).strip()
    if not s:
        return df
    if s == "1":
        return df
    try:
        obj: Any = json.loads(s)
        if isinstance(obj, dict):
            fid = (obj.get("flow_id") or "").strip()
            if fid:
                return fid
    except Exception:
        pass
    return df
