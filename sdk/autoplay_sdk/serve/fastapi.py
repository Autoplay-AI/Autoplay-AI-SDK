"""FastAPI factory for self-hosted chatbot bridge deployments."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable

from autoplay_sdk.async_client import AsyncConnectorClient
from autoplay_sdk.chat_pipeline import compose_chat_pipeline
from autoplay_sdk.prompts import RAG_SYSTEM_PROMPT
from autoplay_sdk.user_index import UserSessionIndex

LlmCallable = Callable[[str], Awaitable[str]]


def build_copilot_app(
    *,
    stream_url: str,
    token: str,
    llm: LlmCallable,
    summary_threshold: int = 10,
    lookback_seconds: float = 300.0,
    system_prompt: str | None = None,
):
    """Build a minimal FastAPI app that bridges stream events to user-keyed replies."""
    try:
        from fastapi import FastAPI, HTTPException
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "FastAPI is required for autoplay_sdk.serve. Install with: pip install autoplay-sdk[serve]"
        ) from exc

    pipeline = compose_chat_pipeline(
        llm=llm,
        threshold=summary_threshold,
        lookback_seconds=lookback_seconds,
    )
    user_index = UserSessionIndex(
        context_store=pipeline.context_store,
        lookback_seconds=lookback_seconds,
    )
    session_states: dict[str, object] = {}
    run_task: asyncio.Task | None = None
    client = AsyncConnectorClient(url=stream_url, token=token)
    prompt_text = system_prompt or RAG_SYSTEM_PROMPT["content"]

    async def on_actions(payload):
        await pipeline.on_actions(payload)
        user_index.add(payload)
        if payload.user_id:
            from autoplay_sdk.agent_state_v2 import SessionState

            session_states.setdefault(payload.user_id, SessionState())

    @asynccontextmanager
    async def lifespan(_app):
        nonlocal run_task
        client.on_actions(on_actions)
        run_task = client.run_in_background()
        try:
            yield
        finally:
            client.stop()
            if run_task is not None:
                await run_task

    app = FastAPI(lifespan=lifespan)
    app.state.pipeline = pipeline
    app.state.user_index = user_index
    app.state.session_states = session_states
    app.state.connector_client = client

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/context/{user_id}")
    async def context(user_id: str, query: str) -> dict[str, str]:
        activity = user_index.get_user_activity(user_id)
        if not activity:
            raise HTTPException(status_code=404, detail="No activity found for user")
        return {"user_id": user_id, "query": query, "context": activity}

    @app.get("/reply/{user_id}")
    async def reply(user_id: str, query: str) -> dict[str, str]:
        activity = user_index.get_user_activity(user_id)
        if not activity:
            raise HTTPException(status_code=404, detail="No activity found for user")
        prompt = (
            f"{prompt_text}\n\n"
            f"[User ID]\n{user_id}\n\n"
            f"[Recent activity]\n{activity}\n\n"
            f"[User query]\n{query}"
        )
        answer = await llm(prompt)
        return {
            "user_id": user_id,
            "query": query,
            "reply": answer,
            "context": activity,
        }

    @app.post("/admin/reset/{user_id}")
    async def reset_user(user_id: str) -> dict[str, str]:
        user_index.reset_user(user_id)
        session_states.pop(user_id, None)
        return {"status": "ok", "user_id": user_id}

    return app


__all__ = ["build_copilot_app"]
