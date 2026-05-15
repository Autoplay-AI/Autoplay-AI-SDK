---
name: autoplay-core
description: >-
  Sets up the Autoplay SDK for real-time event streaming into any chatbot or AI agent.
  Covers install, credentials, stream wiring, LLM guardrails, and the two most critical
  concepts — session scoping and conversation scoping — that must be correct regardless
  of which chatbot or activity source is used. Use when starting any Autoplay integration,
  when the user mentions autoplay-sdk, AsyncConnectorClient, ActionsPayload, or asks how
  to wire real-time user events into a chatbot.
disable-model-invocation: true
---

# Autoplay Core

## Install

```bash
pip install autoplay-sdk
# Optional: one-line FastAPI bridge
# pip install "autoplay-sdk[serve]"
# Plus your preferred LLM client, e.g.:
#   pip install openai        # OpenAI / Azure OpenAI
#   pip install anthropic     # Anthropic Claude
#   pip install google-generativeai  # Gemini
```

Credentials come from the Autoplay dashboard after running `onboard_product`:
- `CONNECTOR_URL` — stream URL: `https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID`
- `API_TOKEN` — Bearer token (Unkey key)

---

## ⚠️ Critical: Session scoping & conversation scoping

**This is the most important concept. Get this wrong and context will be empty, mixed between users, or silently dropped.**

### Session scoping

Every `ActionsPayload` carries a `session_id`. This is the per-user bucket key.

- `session_id` may be `None` before identity linking — always guard: `if not payload.session_id: return`
- Buffer and deliver events keyed **only** by `session_id` — never mix events from different users
- Pick one user key (`user_id` preferred, fallback to `session_id`) and use it **end-to-end** in your chatbot layer
- If you use `email`, fall back to `session_id` for anonymous users
- For widget-based bots, explicitly map PostHog `distinct_id`/`user_id` to widget metadata and chatbot `sender_id`
- If payloads include `product_id` (common), preserve it and pass it on retrieval (`context_store.get(..., product_id=...)`)

### Conversation scoping

The browser `session_id` must be linked to the chatbot platform's `conversation_id`.

```python
# Canonical pattern — one dict per product worker
conv_map: dict[str, str] = {}  # session_id → conversation_id
```

Rules:
- `write_actions_cb` **must** guard: `conv_id = conv_map.get(session_id); if not conv_id: return`
- Call `await writer.on_session_linked(session_id, conversation_id)` the moment the link is known — this flushes the pre-link buffer as a single batched note
- The first successful link is **sticky** — never re-link the same session
- Actions that arrive before the link are buffered automatically by `BaseChatbotWriter`, not dropped

**Chatbots without a persistent `conversation_id`** (e.g. Ada `metaFields`, Dify KB): scope via a context store keyed by `session_id` served from a FastAPI endpoint — no `conv_map` needed.

**What breaks without correct scoping:**
- Wrong user's events delivered to wrong conversation
- Empty context because retrieval key doesn't match storage key
- Pre-link actions silently dropped

---

## Fastest SDK-native path (recommended)

```python
import asyncio
from autoplay_sdk import AsyncConnectorClient, compose_chat_pipeline
from autoplay_sdk.user_index import UserSessionIndex

CONNECTOR_URL = "https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID"
API_TOKEN = "your-api-token"

async def llm(prompt: str) -> str:
    """Wire your preferred LLM here.

    The SDK only needs an async callable: (str) -> str.
    Any provider works — OpenAI, Anthropic, Gemini, Mistral, a local model, etc.

    OpenAI example:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI()
        r = await _client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}])
        return r.choices[0].message.content
    """
    raise NotImplementedError("Replace with your LLM client")

# Compose summarizer + context store + writer safely (no callback clobbering)
pipeline = compose_chat_pipeline(
    llm=llm,
    threshold=20,
    lookback_seconds=300,
    max_actions=20,
    write_actions=None,           # optional push callback for chatbot notes
    overwrite_with_summary=None,  # optional summary overwrite callback
)
user_index = UserSessionIndex(pipeline.context_store, lookback_seconds=300)

async def run():
    async with AsyncConnectorClient(url=CONNECTOR_URL, token=API_TOKEN) as client:
        async def on_actions(payload):
            await pipeline.on_actions(payload)
            user_index.add(payload)

        client.on_actions(on_actions)
        await client.run()

asyncio.run(run())
```

When your chatbot gets a `user_id`, call:

```python
activity = user_index.get_user_activity(user_id)
```

This avoids hand-rolled `user_id -> session_id` indexing and keeps `product_id`-aware lookups correct.

---

## Optional one-line HTTP bridge

If your chatbot runtime is in another process (Rasa/Botpress/Twilio/custom webhook), prefer the built-in FastAPI factory:

```python
from autoplay_sdk.serve import build_copilot_app

app = build_copilot_app(
    stream_url=CONNECTOR_URL,
    token=API_TOKEN,
    llm=llm,
    summary_threshold=20,
    lookback_seconds=300,
)
```

Default endpoints:
- `GET /healthz`
- `GET /context/{user_id}?query=...`
- `GET /reply/{user_id}?query=...`
- `POST /admin/reset/{user_id}`

---

## LLM guardrails

Use versioned prompt metadata with your provider client. The SDK does not currently ship a `call_llm(...)` helper.

```python
# GOOD — use prompt metadata alongside your provider call
MY_PROMPT = {
    "name": "Support Answer Prompt",
    "version": "0.1",
    "description": "Answer user questions with product-aware context",
    "content": "You are a helpful assistant...\n\n{context}",
}

messages = [{"role": "system", "content": MY_PROMPT["content"].format(context=context_text)}]
response = await openai_client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
)

# BAD — inline prompt string with no version metadata
response = await openai_client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": "You are a helpful assistant..."}],
)
```

Prompt files live in `src/llm/` only. Each exports:
```python
MY_PROMPT = {
    "name": "My Prompt",
    "version": "0.1",
    "description": "...",
    "content": "...",
}
```

Log: prompt name + version, model, token usage, latency, errors. Never log full session payloads.

---

## Reference

- Quickstart: https://developers.autoplay.ai/quickstart
- SDK overview: https://developers.autoplay.ai/sdk/overview
- Chatbot tutorials: https://developers.autoplay.ai/recipes/intercom-tutorial
