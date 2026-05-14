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
- Pick one key (`session_id` or `email`) and use it **end-to-end**: store with it, retrieve with it, pass it to the chatbot
- If you use `email`, fall back to `session_id` for anonymous users

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

## Core wiring pattern

```python
import asyncio
from autoplay_sdk import AsyncConnectorClient, AsyncSessionSummarizer
from autoplay_sdk.agent_context import AsyncAgentContextWriter

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

# --- implement these two callbacks for your chatbot platform ---

async def write_actions_cb(session_id: str, text: str) -> None:
    # Called ~every 3s with formatted action list
    # Guard on conv_map.get(session_id) if your platform needs a conversation_id
    ...

async def overwrite_cb(session_id: str, summary: str) -> None:
    # Called after threshold actions with LLM summary
    # Post summary first, then redact old action notes
    ...

# --- wire it together ---

agent_writer = AsyncAgentContextWriter(
    summarizer=AsyncSessionSummarizer(llm=llm, threshold=20),
    write_actions=write_actions_cb,
    overwrite_with_summary=overwrite_cb,
    debounce_ms=0,
)

async def run():
    async with AsyncConnectorClient(url=CONNECTOR_URL, token=API_TOKEN) as client:
        client.on_actions(agent_writer.add)
        await client.run()

asyncio.run(run())
```

---

## LLM guardrails

All LLM calls must go through `call_llm` with `prompt_meta` — never inline strings or raw provider calls without versioning:

```python
# GOOD — provider-agnostic, versioned
content, meta = call_llm(
    model=LLM_MODEL,          # any model string your provider accepts
    messages=[{"role": "system", "content": prompt_text}],
    prompt_meta=MY_PROMPT,    # has name, version
)

# BAD — hardcoded provider, inline prompt, no versioning
response = openai.chat.completions.create(
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
