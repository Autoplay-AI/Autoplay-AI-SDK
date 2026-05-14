from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.chat_pipeline import compose_chat_pipeline  # noqa: E402
from autoplay_sdk.models import ActionsPayload, SlimAction  # noqa: E402


def _payload() -> ActionsPayload:
    return ActionsPayload(
        product_id="prod",
        session_id="sess",
        user_id="user",
        email="user@example.com",
        actions=[SlimAction(title="t", description="clicked", canonical_url="/x")],
        count=1,
        forwarded_at=time.time(),
    )


@pytest.mark.asyncio
async def test_compose_chat_pipeline_fanout_summary_to_context_and_writer() -> None:
    writes: list[str] = []
    summaries: list[str] = []

    async def llm(_prompt: str) -> str:
        return "short summary"

    async def write_actions(_session_id: str, text: str) -> None:
        writes.append(text)

    async def overwrite(_session_id: str, summary: str) -> None:
        summaries.append(summary)

    pipeline = compose_chat_pipeline(
        llm=llm,
        threshold=1,
        write_actions=write_actions,
        overwrite_with_summary=overwrite,
    )

    await pipeline.on_actions(_payload())
    await pipeline.summarizer.flush()

    assert writes
    assert summaries == ["short summary"]
    assert "Summary: short summary" in pipeline.context_store.get("sess")
