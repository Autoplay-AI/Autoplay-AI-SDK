from __future__ import annotations

import asyncio
import time
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.models import ActionsPayload, SlimAction  # noqa: E402
from autoplay_sdk.serve import fastapi as serve_fastapi  # noqa: E402


class _DummyClient:
    def __init__(self, url: str, token: str) -> None:
        self._cb = None

    def on_actions(self, cb):
        self._cb = cb
        return self

    def run_in_background(self):
        return asyncio.get_running_loop().create_task(asyncio.sleep(0))

    def stop(self) -> None:
        return


def _payload() -> ActionsPayload:
    return ActionsPayload(
        product_id="prod",
        session_id="sess",
        user_id="u1",
        email="u1@example.com",
        actions=[SlimAction(title="t", description="clicked X", canonical_url="/x")],
        count=1,
        forwarded_at=time.time(),
    )


def test_build_copilot_app_exposes_health_context_and_reply(monkeypatch) -> None:
    monkeypatch.setattr(serve_fastapi, "AsyncConnectorClient", _DummyClient)

    async def llm(prompt: str) -> str:
        return f"ok:{'clicked X' in prompt}"

    app = serve_fastapi.build_copilot_app(
        stream_url="http://example.com/stream/prod",
        token="tok",
        llm=llm,
    )

    async def _prime() -> None:
        payload = _payload()
        await app.state.pipeline.on_actions(payload)
        app.state.user_index.add(payload)

    asyncio.run(_prime())

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        context_resp = client.get("/context/u1", params={"query": "what happened"})
        assert context_resp.status_code == 200
        reply_resp = client.get("/reply/u1", params={"query": "what happened"})
        assert reply_resp.status_code == 200
        assert reply_resp.json()["reply"].startswith("ok:")
