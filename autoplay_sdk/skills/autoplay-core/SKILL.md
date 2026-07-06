---
name: autoplay-core
description: >-
  Sets up the Autoplay SDK for real-time user context in any chatbot or AI agent.
  Covers install, credentials from onboard_product (ingest_url/ingest_secret/mcp_url/mcp_key),
  the on-demand REST/MCP pull pattern that powers Intercom/Crisp/Dify/Tidio/Maven/Ada/
  Botpress/Landbot, the legacy Render push/session-linking pattern that still powers Zendesk,
  LLM guardrails, and the two most critical concepts — session scoping and conversation
  scoping — for the push track. Use when starting any Autoplay integration, when the user
  mentions autoplay-sdk, mcp_key, AsyncConnectorClient, ActionsPayload, or asks how to wire
  real-time user events into a chatbot.
disable-model-invocation: true
---

# Autoplay Core

## Install

```bash
pip install autoplay-sdk
# Optional: one-line FastAPI bridge (legacy push path only — see below)
# pip install "autoplay-sdk[serve]"
# Plus your preferred LLM client, e.g.:
#   pip install openai        # OpenAI / Azure OpenAI
#   pip install anthropic     # Anthropic Claude
#   pip install google-generativeai  # Gemini
```

Upgrading an existing integration? Install the migration helper skill and ask your agent to rewrite deprecated imports:

```bash
autoplay-install-skills --migrate
```

Credentials come from running `onboard_product` (see the Quickstart):

```python
from autoplay_sdk.admin import onboard_product
from autoplay_sdk.providers import PostHogProvider  # or AmplitudeProvider

result = await onboard_product(
    "YOUR_PRODUCT_ID",
    contact_email="you@yourcompany.com",
    user_activity_provider=PostHogProvider(),
    print_operator_summary=True,
)
```

It prints six values:
- `product_id`, `provider`
- `ingest_url` — where your activity source (PostHog/Amplitude) POSTs events, e.g. `https://connector.autoplay.ai/ingest/YOUR_PRODUCT_ID`
- `ingest_secret` — the inbound auth secret for that webhook
- `mcp_url` — always `https://mcp.autoplay.ai/mcp`
- `mcp_key` — Bearer token for both the MCP tool call and the REST live-activity read below

There is no more `stream_url` / `unkey_key` — those were the legacy Render fields. If you're touching an existing Render-onboarded product (see **Push/session-linking path**, below), it keeps its old `stream_url` and `unkey_key`; new products only get `ingest_*` / `mcp_*`.

---

## Which path does this integration need?

Two integration models exist. **Pick the pull-based path unless you know you need the push path** — it is simpler, requires no server process for the reactive case, and is what every currently-migrated chatbot skill in this repo (`chatbot-ada`, `chatbot-botpress`, `chatbot-intercom`, `chatbot-landbot`) uses.

| | **Pull-based (current default)** | **Push / session-linking (legacy Render)** |
|---|---|---|
| Data flow | Chatbot (or your bridge) asks for a user's recent activity **on demand**, the moment it needs context to answer | Autoplay pushes every action over a live stream; your server buffers it and posts it as a note/message once a conversation links |
| Transport | `GET https://mcp.autoplay.ai/users/{product_id}/{user_id}/live-activity` (REST) or the MCP tool `get_live_user_activity` | `AsyncConnectorClient` / `ConnectorClient` subscribed to a Render `stream_url` |
| Keyed by | `user_id` only — no session concept | `session_id` (ground truth from PostHog) linked to `conversation_id` |
| Use when | The chatbot platform can call an MCP tool or your backend can make an outbound HTTP call at question-time (Intercom Fin, Crisp Hugo, Dify Agent, Tidio Lyro, Maven, or any custom bridge — see that platform's own `chatbot-*` skill) | The integration must autonomously **post** admin notes or proactive messages without an LLM deciding to call a tool (this is how the current Zendesk integration works — see `chatbot-zendesk`) |
| Needs a persistent process? | No — a single HTTP call per question | Yes — something has to hold the stream open (or, for a self-built proactive poller, run a periodic pull loop keyed by `user_id`; see the Rasa/Inkeep recipes for that pattern) |

If you're not sure which one your customer's platform needs, check whether a `chatbot-<platform>` skill already exists — it tells you which model that platform uses today.

---

## Pull-based path (recommended default)

No client object, no background task — just call the connector when you need the answer.

```python
import httpx

CONNECTOR_URL = "https://mcp.autoplay.ai"  # origin of mcp_url, no /mcp path
PRODUCT_ID = "YOUR_PRODUCT_ID"
MCP_KEY = "YOUR_MCP_KEY"  # from onboard_product

async def get_live_activity(user_id: str, limit: int = 20) -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            f"{CONNECTOR_URL}/users/{PRODUCT_ID}/{user_id}/live-activity",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {MCP_KEY}"},
        )
    if r.status_code != 200:
        return []
    return r.json().get("actions", [])  # oldest -> newest
```

- `user_id` **must** be the same stable id your activity source identifies the user with (`posthog.identify(user_id)` / `amplitude.setUserId(user_id)`) — never email or a session id.
- If the chatbot platform supports MCP tools directly (Intercom, Crisp, Dify, Tidio, Maven), skip the HTTP call entirely and point the platform's MCP config at `mcp_url` with `mcp_key` — it calls `get_live_user_activity` itself. See that platform's `chatbot-*` skill.
- If it doesn't (Landbot, Botpress, Rasa, a custom widget), your bridge makes the call above synchronously inside whatever handler needs the answer (a webhook, a `/reply` endpoint, a context-fetch before opening the widget). No `AsyncConnectorClient`, no session store, no summarizer required — the endpoint already returns a bounded, recent window of actions.
- For **proactive** behaviour on this path (nudge the user before they ask), there's no push signal to react to — poll the same endpoint on a timer for each user you're tracking and evaluate your own trigger condition against the returned `actions`. See `autoplay_sdk.proactive_triggers` (`ProactiveTriggerContext`, `ProactiveTriggerRegistry`) for the predicate/FSM primitives; the Rasa and Inkeep recipes show the full poller pattern.

---

## Push / session-linking path (legacy Render)

Everything below this line assumes a **Render-onboarded product with a `stream_url`** — i.e. the older `autoplay_sdk.admin.onboard` / `product_onboarding` registration flow, not the current `onboard_product`. This is the path `chatbot-zendesk` uses today because Zendesk's integration autonomously posts admin notes and public replies with no LLM tool call involved. Don't reach for this path for a new pull-capable integration.

### Recommended entry point — `AutoplayChatbotManager`

`AutoplayChatbotManager` handles all session lifecycle automatically. Use it unless you need custom Redis-backed stores or non-standard delivery logic.

```python
from autoplay_sdk import AutoplayChatbotManager, BaseChatbotWriter

# 1. Implement _post_note — the only platform-specific code
class MyWriter(BaseChatbotWriter):
    async def _post_note(self, conversation_id: str, text: str) -> None:
        # call your chatbot platform's API here
        ...

# 2. Initialize once at server startup
manager = AutoplayChatbotManager(writer=MyWriter())

# 3. Autoplay stream handler — identical for every platform
async def on_actions(payload):
    await manager.on_actions(payload)

# 4. Chatbot webhook handler — only the extraction lines differ per platform
async def on_webhook(data):
    session_id = data["custom_attributes"]["session_id"]  # ← platform-specific
    conversation_id = data["id"]                          # ← platform-specific
    await manager.on_chatbot_event(session_id, conversation_id)
```

**That's it.** The manager handles:
- Creating `SessionState` the moment a `session_id` is first seen (PostHog is the ground truth)
- Buffering actions before a conversation is linked
- Auto-detecting `NEW` vs `REPLY_EXISTING` from the link store
- Flushing buffered actions the moment the link is established
- Routing all future delivery to `conversation_id` permanently

`session_id` comes from PostHog. `conversation_id` comes from the chatbot platform. They are married together by `on_chatbot_event`. After that call, all proactive triggers, reactive notes, and future actions route to that conversation for the lifetime of the session.

---

### Low-level building blocks (advanced use)

Use these directly only when you need custom Redis-backed stores or non-standard delivery.

```python
from autoplay_sdk import (
    InMemorySessionStateStore,
    InMemoryConversationLinkStore,
    link_conversation,
)
from autoplay_sdk.agent_state.v2 import SessionState

# Initialize stores at server startup
session_store = InMemorySessionStateStore()
link_store = InMemoryConversationLinkStore()

# Phase 1 — Autoplay stream: SessionState born here, session_id is the ground truth
async def on_actions(payload):
    if not payload.session_id:
        return
    state = await session_store.get_or_create(payload.session_id)  # ← first, always
    await writer.write_actions(...)

# Phase 2 — Chatbot webhook: look up existing state, add conversation_id
async def on_webhook(data):
    session_id = data["custom_attributes"]["session_id"]  # platform-specific
    conversation_id = data["id"]                          # platform-specific
    state = await session_store.get_or_create(session_id)
    link_conversation(state=state, store=link_store, conversation_id=conversation_id)
    await writer.on_session_linked(session_id, conversation_id)
```

`SessionState` fields:
- `state.session_id` — mandatory required field; `SessionState(session_id=...)` — construction without it is a `TypeError`
- `state.metadata` — optional extras (`user_id`, `email`, any future fields)
- `state.conversation_linked` / `state.conversation_id` — linked chatbot conversation
- `state.current_state` — FSM (THINKING / PROACTIVE / REACTIVE)

**Production: swap to Redis-backed store**

`InMemorySessionStateStore` loses all state on restart. For production, use `RedisSessionStateStore` — sessions survive restarts and scale across instances. It is a drop-in replacement:

```python
# Install the redis extra
# pip install "autoplay-sdk[redis]"

from autoplay_sdk import AutoplayChatbotManager, RedisSessionStateStore

# One-line swap at server startup
manager = AutoplayChatbotManager(
    writer=MyWriter(),
    session_store=RedisSessionStateStore(redis_url=os.environ["REDIS_URL"]),
)
```

Key pattern: `autoplay:session_state:{session_id}`. Default TTL: 24 h (configurable via `ttl_s`). On Redis errors, falls back gracefully and logs a warning — never crashes.

**What breaks without correct scoping:**
- Wrong user's events delivered to wrong conversation
- Empty context because retrieval key doesn't match storage key
- Pre-link actions silently dropped

---

### Raw stream client (advanced / analytics-only)

If you only need to receive enriched events and forward them to your own pipeline — no chatbot, no notes, no session linking — you need none of the chatbot-shaped machinery above. Just the client, against a legacy Render `stream_url`:

```python
import asyncio
from autoplay_sdk import AsyncConnectorClient

STREAM_URL = "https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID"  # legacy Render only
API_TOKEN = "your-unkey-token"

async def run():
    async with AsyncConnectorClient(url=STREAM_URL, token=API_TOKEN) as client:
        async def on_actions(payload):
            if not payload.session_id:
                return
            # payload.slim_actions  — list of enriched action dicts
            # payload.user_id       — set if posthog.identify() was called
            # payload.email         — set if posthog.identify() was called
            your_downstream(payload)  # push to PostHog, Segment, your DB, etc.

        client.on_actions(on_actions)
        await client.run()

asyncio.run(run())
```

No `BaseChatbotWriter`, no session store required. This only works against a product still registered on the legacy Render connector — new `onboard_product` registrations don't get a `stream_url`.

---

### Optional one-line HTTP bridge (legacy Render only)

`autoplay_sdk.api.build_copilot_app` is a FastAPI factory for the push path — its signature still takes `stream_url` / `token`, not `mcp_url` / `mcp_key`:

```python
from autoplay_sdk.api import build_copilot_app

app = build_copilot_app(
    stream_url=STREAM_URL,   # legacy Render stream — see above
    token=API_TOKEN,
    llm=llm,
    summary_threshold=20,
    lookback_seconds=300,
)
```

Default endpoints: `GET /healthz`, `GET /context/{user_id}?query=...`, `GET /reply/{user_id}?query=...`, `POST /admin/reset/{user_id}`.

**This factory has not been updated for the pull-based path.** For a new integration that needs its own HTTP bridge (Rasa, Botpress, Landbot, a custom widget), hand-roll a small FastAPI app with a `/context/{user_id}` and/or `/reply/{user_id}` route that calls the pull-based `get_live_activity(user_id)` helper above synchronously — see the Rasa or Inkeep recipes for the full pattern. It's a handful of lines and doesn't need this factory.

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

## Integration Self-Reasoning Checklist (push / session-linking path only)

**This checklist applies to the push/session-linking path above (`AutoplayChatbotManager`, `BaseChatbotWriter`, `SessionState`).** If you're on the pull-based path (the default — no session store, no stream client), skip this section entirely: there's no session to scope, no webhook race to reason about, and no FSM persistence to wire up. Just make sure the `user_id` you pass to the live-activity read matches the id your activity source identifies the user with.

**Run through this checklist before considering any push-path chatbot integration complete. Reason through each question — do not skip.**

### 1. Session identity

- Is `session_id` the **first** thing set in `SessionState`?
  `state = SessionState(session_id=...)` — `SessionState()` without `session_id` is a `TypeError`.
- Is **PostHog** the ground truth for `session_id`? It must come from `ActionsPayload.session_id`, never from the chatbot platform.
- Is `await session_store.get_or_create(session_id)` the **very first `await`** in every handler — before any processing, delivery, or API call?
- Does `state.metadata` carry all optional identity context (`user_id`, `email`, etc.)? Nothing important should live outside `SessionState`.

### 2. Race conditions

- **Webhook fires before stream:** `get_or_create` handles this — it creates the state with `session_id` set. Actions that arrive later from the stream route correctly because the state already exists.
- **Stream fires before webhook:** Actions buffer in `BaseChatbotWriter._pending` until `on_session_linked` is called. Nothing is dropped.
- **Concurrent webhooks for the same session:** `InMemorySessionStateStore.get_or_create` is a synchronous dict operation — race-safe. `RedisSessionStateStore` does a GET-before-SET — acceptable for session context (last writer wins on the rare collision).
- **Session state missing after restart:** If using `InMemorySessionStateStore` in production, state is lost. Switch to `RedisSessionStateStore`.

### 3. Chatbot linking

- Is `link_conversation(state=state, store=store, conversation_id=conv_id)` called with no `event=` argument? Let it auto-detect `NEW` vs `REPLY_EXISTING` from the store.
- Is `await writer.on_session_linked(session_id, conversation_id)` called **immediately after** `link_conversation`? This is the flush trigger — without it, buffered actions are never delivered.
- Is the link **sticky**? Once `state.conversation_linked == True`, the same session must not be re-linked to a different `conversation_id`. The `REPLY_EXISTING` semantics handle this automatically — but verify the webhook handler is not calling `link_conversation` again on subsequent replies.
- If using `RedisSessionStateStore`: is `await session_store.save(state)` called after linking? `AutoplayChatbotManager.on_chatbot_event` does this automatically — verify if using the low-level path.

### 4. Proactive triggers

- Are proactive triggers reading `state.conversation_id` as the delivery target?
- Is there a guard: `if not state.conversation_linked: return` before calling the chatbot API? A trigger that fires before the conversation is linked has nowhere to deliver.
- Does the FSM gate the trigger correctly? Call `state.tick()` first, then `allowed, reason = state.can_deliver_proactive()`. This is the canonical check — it verifies both `THINKING` state and cooldown simultaneously. Do not replicate this logic inline.
- After delivering a proactive trigger, is the FSM transitioned? `state.transition_to_proactive(trigger_id)` must be called or the session stays in THINKING and the trigger may re-fire.
- After any FSM transition (`to_proactive`, `to_reactive`, `tick`, `start_cooldown`), is `await manager.save_state(state)` called?
  `on_actions` and `on_chatbot_event` auto-save — but external FSM mutations require an explicit `save_state` call:
  ```python
  state.to_proactive(session_id=state.session_id, ...)
  await manager.save_state(state)   # persist PROACTIVE FSM state to Redis
  ```

### 5. Persistence (production)

- On first `session_id` arrival, `get_or_create` creates and immediately persists `SessionState` to Redis. This is the ground truth — everything else builds on it.
- `on_actions` does NOT save state — it only reads `state.conversation_id` for routing and passes actions to the writer. `SessionState` is not mutated by action delivery.
- `on_chatbot_event` always saves after linking — `conversation_linked` and `conversation_id` are the mutations that need persistence there.
- For any FSM mutation that happens **outside** `on_chatbot_event`, call `await manager.save_state(state)`. This covers: `to_proactive`, `to_reactive`, `tick`, `start_cooldown`, `record_user_interaction`, and any `metadata` update.
- Is `InMemorySessionStateStore` replaced with `RedisSessionStateStore` in production?
  ```python
  # pip install "autoplay-sdk[redis]"
  manager = AutoplayChatbotManager(
      writer=MyWriter(),
      session_store=RedisSessionStateStore(redis_url=os.environ["REDIS_URL"]),
  )
  ```
- Is `REDIS_URL` set in the production environment?
- Is the TTL appropriate? Default is 24 h (`ttl_s=86400`). Sessions longer than the TTL will lose state.

### Smoke test — verify the full hop before going to production (push path)

```bash
# Run from your project root after setting STREAM_URL and API_TOKEN:
python -m autoplay_sdk.smoke_test \
    --url "$STREAM_URL" \
    --token "$API_TOKEN"
# Expected output:
#   ✓ connection  — stream connected
#   ✓ heartbeat   — first ActionsPayload received within 10 s
#   ✓ session_id  — payload.session_id is non-empty
```

If `session_id` is empty at this stage, PostHog `identify()` has not fired yet —
see `activity-posthog` Step 2.

For the pull-based path, there's no stream to smoke-test — just curl the live-activity endpoint directly:

```bash
curl "https://mcp.autoplay.ai/users/YOUR_PRODUCT_ID/YOUR_USER_ID/live-activity?limit=10" \
  -H "Authorization: Bearer YOUR_MCP_KEY"
```

A `200` with a populated `actions` array means it's working.

---

## Reference

- Quickstart: https://developers.autoplay.ai/quickstart
- SDK overview: https://developers.autoplay.ai/sdk/overview
- Chatbot tutorials: https://developers.autoplay.ai/recipes/intercom-tutorial
