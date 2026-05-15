from __future__ import annotations

import sys
import time
from pathlib import Path

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.context_store import ContextStore  # noqa: E402
from autoplay_sdk.models import ActionsPayload, SlimAction  # noqa: E402
from autoplay_sdk.user_index import UserSessionIndex  # noqa: E402


def _payload(
    *, user_id: str, session_id: str, product_id: str, text: str
) -> ActionsPayload:
    now = time.time()
    return ActionsPayload(
        product_id=product_id,
        session_id=session_id,
        user_id=user_id,
        email=f"{user_id}@example.com",
        actions=[SlimAction(title="t", description=text, canonical_url="/x")],
        count=1,
        forwarded_at=now,
    )


def test_user_session_index_tracks_recent_sessions() -> None:
    store = ContextStore()
    idx = UserSessionIndex(store, lookback_seconds=300, max_sessions_per_user=5)
    p1 = _payload(user_id="u1", session_id="s1", product_id="p1", text="did one")
    p2 = _payload(user_id="u1", session_id="s2", product_id="p1", text="did two")

    store.add(p1)
    store.add(p2)
    idx.add(p1)
    idx.add(p2)

    sessions = idx.get_recent_sessions("u1")
    assert [s.session_id for s in sessions] == ["s2", "s1"]
    assert idx.get_email("u1") == "u1@example.com"


def test_user_session_index_aggregates_activity_across_sessions() -> None:
    store = ContextStore()
    idx = UserSessionIndex(store, lookback_seconds=300, max_sessions_per_user=5)
    p1 = _payload(user_id="u2", session_id="s10", product_id="p2", text="alpha")
    p2 = _payload(user_id="u2", session_id="s11", product_id="p2", text="beta")

    store.add(p1)
    store.add(p2)
    idx.add(p1)
    idx.add(p2)

    text = idx.get_user_activity("u2")
    assert "Session s10" in text
    assert "Session s11" in text
    assert "alpha" in text
    assert "beta" in text
