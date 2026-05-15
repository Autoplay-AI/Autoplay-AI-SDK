# autoplay-sdk

Real-time event streaming client for [Autoplay](https://autoplay.so) connectors.

Receive live UI actions and session summaries from the Autoplay event connector
via SSE (Server-Sent Events) — ideal as a real-time data source for RAG
pipelines, analytics systems, or custom automation.

---

## Installation

```bash
pip install autoplay-sdk
```

**Requirements:** Python 3.10+

---

## Components (state models)

```text
agent_states      — session FSM (v1, 5 states, deprecated)
agent_state_v2    — session FSM (v2, 3 states, recommended for new code)
```

---

## Two RAG surfaces (don’t confuse them)

Most chatbot integrations use both surfaces in sequence:
1. `ContextStore.enrich(...)` to build retrieval text for embeddings/vector search.
2. `assemble_rag_chat_context(...)` to build structured chat prompts for the reply model.

| Module | Purpose |
|--------|--------|
| **`autoplay_sdk.rag`** — `RagPipeline` / `AsyncRagPipeline` | **Ingestion:** embed events + upsert into a **vector store** from the live stream. |
| **`autoplay_sdk.rag_query`** — `assemble_rag_chat_context`, formatters, `prompts`, **`rag_query.watermark`** | **Query-time chat:** build the **user message block** and **system prompt text** for an LLM from **user query**, **real-time activity**, **conversation history**, and **optional** KB — swap memory/KB via **`ChatMemoryProvider`** / **`KnowledgeBaseRetriever`**. Use **`InboundWatermarkStore`** + **`cutoff_for_delta_activity`** to drive **activity since last user message** on follow-up turns. |

Use **`ContextStore.enrich()`** for retrieval-query text and **`rag_query`** for final chat prompt assembly.

For **which loggers to tune** and **safe structured `extra` fields** when debugging `rag_query` in production, see **`docs/sdk/logging.mdx`**.

---

## Query-time RAG enrichment (primary use case)

The most common use case is enriching a user's query with their live session
context — recent UI actions and an LLM-generated rolling summary — before
sending the query to your vector database.

`ContextStore` (or `AsyncContextStore`) accumulates that context in memory and
exposes a single `enrich()` call:

```python
enriched = context_store.enrich(session_id, user_message)
results  = vector_db.query(embed(enriched))
```

### Setup

```python
from autoplay_sdk import AsyncConnectorClient
from autoplay_sdk.summarizer import AsyncSessionSummarizer
from autoplay_sdk.context_store import AsyncContextStore

# Summarise after every 10 actions (optional but recommended)
summarizer = AsyncSessionSummarizer(llm=my_async_llm, threshold=10)

# Keep only the last 5 minutes of actions; cap at 20 per query
context_store = AsyncContextStore(
    summarizer=summarizer,
    lookback_seconds=300,
    max_actions=20,
)

# IMPORTANT: if events are ingested with product_id (default in connector payloads),
# pass the same product_id to get()/enrich()/reset() calls.

# Wire the client — one line each
client = AsyncConnectorClient(url=STREAM_URL, token=API_TOKEN)
client.on_actions(context_store.add)
task = client.run_in_background()
```

### In your chatbot handler

```python
async def chat(session_id: str, product_id: str, user_message: str) -> str:
    enriched = context_store.enrich(session_id, user_message, product_id=product_id)
    results  = await vector_db.query(await embed(enriched))
    return await llm(results, user_message)
```

**Output format** (context is injected before the query):

```
[Session context]
Summary: User navigated to the Dashboard and exported a CSV.

Recent activity:
1. Opened billing settings — /settings/billing
2. Clicked Upgrade plan — /settings/billing

[Query]
How do I add a team member?
```

If no context exists for a session, `enrich()` returns the raw query unchanged.

### Configuration

All options can be set as defaults at construction time **and** overridden
individually on any `enrich()` / `get()` call:

| Option | Default | Description |
|---|---|---|
| `include_summary` | `True` | Include the rolling LLM summary |
| `include_actions` | `True` | Include pending (not-yet-summarised) actions |
| `lookback_seconds` | `None` | Only include actions within the last N seconds (`forwarded_at` timestamp) |
| `max_actions` | `None` | Cap on the most recent N actions (applied after `lookback_seconds`) |

```python
# Per-call overrides — change behaviour for a single request
context_store.enrich(session_id, query, include_actions=False)   # summaries only
context_store.enrich(session_id, query, include_summary=False)   # actions only
context_store.enrich(session_id, query, lookback_seconds=60)     # last 60 s of actions
context_store.enrich(session_id, query, max_actions=5)           # last 5 actions only
```

### Sync version

```python
from autoplay_sdk import ConnectorClient
from autoplay_sdk.summarizer import SessionSummarizer
from autoplay_sdk.context_store import ContextStore

summarizer    = SessionSummarizer(llm=my_llm, threshold=10)
context_store = ContextStore(summarizer=summarizer, lookback_seconds=300)

client = ConnectorClient(url=STREAM_URL, token=API_TOKEN)
client.on_actions(context_store.add)
client.run_in_background()

def chat(session_id: str, product_id: str, query: str) -> str:
    enriched = context_store.enrich(session_id, query, product_id=product_id)
    results  = vector_db.query(embed(enriched))
    return llm(results, query)
```

---

## Quickstart

```python
from autoplay_sdk import ConnectorClient, ActionsPayload

STREAM_URL = "https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID"
API_TOKEN  = "uk_live_..."
# Or set AUTOPLAY_APP_UNKEY_TOKEN and leave token="".

def on_actions(payload: ActionsPayload):
    print(payload.to_text())

ConnectorClient(url=STREAM_URL, token=API_TOKEN) \
    .on_actions(on_actions) \
    .run()
```

`run()` blocks and reconnects automatically on any network failure.
Press **Ctrl-C** to stop.

---

## Typed payloads

All callbacks receive typed dataclass instances — not raw dicts.  Your IDE
will autocomplete fields and you get a `.to_text()` method on every payload
that returns an embedding-ready string.

```python
from autoplay_sdk import ActionsPayload, SummaryPayload

def on_actions(payload: ActionsPayload):
    print(payload.session_id)       # str | None
    print(payload.email)            # str | None
    print(payload.count)            # int
    for action in payload.actions:
        print(action.title)         # str
        print(action.description)   # str
        print(action.canonical_url) # str

    # embedding-ready text — one call, no formatting logic needed
    text = payload.to_text()
    # "Session ps_abc123 — 3 actions\n1. Viewed Dashboard — https://...\n..."

def on_summary(payload: SummaryPayload):
    print(payload.session_id)
    print(payload.replaces)         # number of actions this summary replaces
    text = payload.to_text()        # the prose summary string directly
```

---

## Background usage (non-blocking)

```python
client = ConnectorClient(url=STREAM_URL, token=API_TOKEN)
client.on_actions(on_actions)
client.run_in_background()

# your application continues here
import time
time.sleep(60)

client.stop()
```

---

## Context manager

```python
with ConnectorClient(url=STREAM_URL, token=API_TOKEN) as client:
    client.on_actions(on_actions).run_in_background()
    do_other_work()
# stop() is called automatically on exit
```

---

## Async RAG pipeline (recommended)

Use `AsyncConnectorClient` when your RAG pipeline is built on `asyncio` —
LangChain, LlamaIndex, FastAPI, or any framework where embedding/vector calls
are already async.

```python
import asyncio
import openai
from autoplay_sdk import AsyncConnectorClient, ActionsPayload, SummaryPayload

openai_client = openai.AsyncOpenAI()

async def on_actions(payload: ActionsPayload):
    """Embed the batch and upsert into your vector store."""
    text = payload.to_text()  # embedding-ready string, no formatting needed
    response = await openai_client.embeddings.create(
        input=text, model="text-embedding-3-small"
    )
    embedding = response.data[0].embedding

    # upsert into Pinecone, Weaviate, Chroma, pgvector, etc.
    await your_vector_store.upsert(
        id=payload.session_id or "unknown",
        vector=embedding,
        metadata={
            "session_id": payload.session_id,
            "email":      payload.email,
            "count":      payload.count,
        },
    )

async def on_summary(payload: SummaryPayload):
    """Replace the raw action history with a compact prose summary."""
    text = payload.to_text()  # the prose summary string directly
    print(f"[summary] session={payload.session_id}: {text}")
    # store in your RAG context window / vector store as well

async def main():
    async with AsyncConnectorClient(url=STREAM_URL, token=API_TOKEN) as client:
        client.on_actions(on_actions).on_summary(on_summary)
        await client.run()

asyncio.run(main())
```

### Non-blocking inside an existing event loop

```python
client = AsyncConnectorClient(url=STREAM_URL, token=API_TOKEN)
client.on_actions(on_actions)
task = client.run_in_background()  # asyncio.Task — returns immediately

await do_other_async_work()

client.stop()
await task
```

## Sync RAG pipeline

If your pipeline is synchronous (no `async/await`), use `ConnectorClient`.
Slow callbacks are safe — the SSE reader and the callback executor run on
separate threads.

```python
import openai
from autoplay_sdk import ConnectorClient, ActionsPayload

openai_client = openai.OpenAI()

def on_actions(payload: ActionsPayload):
    text = payload.to_text()
    embedding = openai_client.embeddings.create(
        input=text, model="text-embedding-3-small"
    ).data[0].embedding
    your_vector_store.upsert(id=payload.session_id or "unknown", vector=embedding)

ConnectorClient(url=STREAM_URL, token=API_TOKEN) \
    .on_actions(on_actions) \
    .run()
```

---

## Drop handling (high-volume)

If your callback is slower than the incoming event rate, events are queued
internally.  When the queue is full, events are dropped.  Register a handler
to be notified:

```python
def on_drop(payload, total_dropped):
    print(f"WARNING: dropped event (type={payload['type']}, total={total_dropped})")
    # alert your on-call rotation, increment a metric, etc.

ConnectorClient(url=STREAM_URL, token=API_TOKEN, max_queue_size=1000) \
    .on_actions(on_actions) \
    .on_drop(on_drop) \
    .run()

# Check the running drop count at any time:
print(client.dropped_count)   # events dropped so far
print(client.queue_size)      # events waiting in the queue right now
```

---

## Payload schemas

Known stream event types:
- `actions` → parsed as `ActionsPayload` and delivered to `on_actions`
- `summary` → parsed as `SummaryPayload` and delivered to `on_summary`
- `heartbeat` (SSE event frame) → ignored as keep-alive
- `usertour_trigger` may appear on connector streams but is currently ignored by SDK clients

### `actions` event

```json
{
  "type":         "actions",
  "product_id":   "my_product",
  "session_id":   "ps_abc123",
  "user_id":      "usr_456",
  "email":        "user@example.com",
  "actions": [
    {
      "title":         "Dashboard",
      "description":   "Viewed the Dashboard page",
      "canonical_url": "https://app.example.com/dashboard"
    },
    {
      "title":         "Export CSV button",
      "description":   "Clicked Export CSV button",
      "canonical_url": "https://app.example.com/dashboard"
    }
  ],
  "count":        2,
  "forwarded_at": 1705314600.123
}
```

| Field                     | Type        | Description                                             |
|---------------------------|-------------|---------------------------------------------------------|
| `type`                    | string      | Always `"actions"`                                      |
| `product_id`              | string      | Connector product identifier                            |
| `session_id`              | string\|null | Unique user session identifier                         |
| `user_id`                 | string\|null | External user identifier (may be `null`)               |
| `email`                   | string\|null | User email if available (may be `null`)                |
| `actions`                 | array       | Ordered list of UI actions in this batch                |
| `actions[].title`         | string      | Human-readable page or element title                    |
| `actions[].description`   | string      | Natural-language description of what the user did       |
| `actions[].canonical_url` | string      | Normalised URL of the page (dynamic segments collapsed) |
| `count`                   | integer     | Number of actions in this batch                         |
| `forwarded_at`            | float       | Unix timestamp when the connector forwarded this batch  |

### `summary` event

```json
{
  "type":         "summary",
  "product_id":   "my_product",
  "session_id":   "ps_abc123",
  "summary":      "The user navigated to the Dashboard, exported a CSV report, then opened account settings to update their billing plan.",
  "replaces":     12,
  "forwarded_at": 1705314900.456
}
```

| Field          | Type        | Description                                              |
|----------------|-------------|----------------------------------------------------------|
| `type`         | string      | Always `"summary"`                                       |
| `product_id`   | string      | Connector product identifier                             |
| `session_id`   | string\|null | Unique user session identifier                          |
| `summary`      | string      | Prose summary of the session up to this point            |
| `replaces`     | integer     | Number of individual actions this summary replaces       |
| `forwarded_at` | float       | Unix timestamp when the connector forwarded this summary |

---

## API reference

### `ContextStore` / `AsyncContextStore`

The primary tool for query-time RAG enrichment.  See the
[Query-time RAG enrichment](#query-time-rag-enrichment-primary-use-case) section
above for a full walkthrough.

**Constructor** — `ContextStore(summarizer=None, *, include_summary=True, include_actions=True, lookback_seconds=None, max_actions=None)`

| Method | Description |
|---|---|
| `.add(payload)` | Store an `ActionsPayload`; wire to `client.on_actions()` |
| `.on_summary(session_id, text)` | Store a summary; auto-wired when `summarizer` is provided |
| `.get(session_id, product_id=..., **overrides)` | Return the formatted context string (`product_id` strongly recommended) |
| `.enrich(session_id, query, product_id=..., **overrides)` | `get()` + append the user query; **primary entry point** |
| `.reset(session_id, product_id=...)` | Clear all context for a session/product bucket |
| `.active_sessions` | Property — list of sessions with stored context |

`AsyncContextStore` has the same interface; `add` and `on_summary` are
coroutines while `get` and `enrich` remain synchronous (safe to call from any
coroutine).

---

### Typed models

| Class | Description |
|-------|-------------|
| `SlimAction` | One UI action: `title`, `description`, `canonical_url` + `.to_text()` |
| `ActionsPayload` | A batch of actions for a session + `.to_text()` for embedding |
| `SummaryPayload` | LLM prose summary for a session + `.to_text()` for embedding |

### `ConnectorClient(url, token="", max_queue_size=500)`

| Parameter       | Type | Default | Description                                            |
|-----------------|------|---------|--------------------------------------------------------|
| `url`           | str  | —       | Full URL to `GET /stream/{product_id}` on the connector |
| `token`         | str  | `""`    | Unkey API key (`uk_live_...`)                          |
| `max_queue_size`| int  | `500`   | Max events buffered before drops start occurring       |

#### Methods

| Method                      | Returns             | Description                                                   |
|-----------------------------|---------------------|---------------------------------------------------------------|
| `.on_actions(fn)`           | `ConnectorClient`   | Register callback; `fn` receives `ActionsPayload`             |
| `.on_summary(fn)`           | `ConnectorClient`   | Register callback; `fn` receives `SummaryPayload`             |
| `.on_drop(fn)`              | `ConnectorClient`   | Register callback when events are dropped (queue full)        |
| `.run()`                    | `None` (blocks)     | Connect and process events; reconnects automatically          |
| `.run_in_background()`      | `threading.Thread`  | Start the client on a daemon thread; returns immediately      |
| `.stop()`                   | `None`              | Signal the client to stop cleanly                             |

#### Properties

| Property        | Type | Description                                          |
|-----------------|------|------------------------------------------------------|
| `dropped_count` | int  | Running total of events dropped due to a full queue  |
| `queue_size`    | int  | Number of events currently waiting in the queue      |

---

### `AsyncConnectorClient(url, token="")`

Async-native client for `asyncio` environments.  Callbacks are `async def` coroutines.

| Parameter | Type | Default | Description                                             |
|-----------|------|---------|---------------------------------------------------------|
| `url`     | str  | —       | Full URL to `GET /stream/{product_id}` on the connector |
| `token`   | str  | `""`    | Unkey API key (`uk_live_...`)                           |

#### Methods

| Method                 | Returns          | Description                                                    |
|------------------------|------------------|----------------------------------------------------------------|
| `.on_actions(fn)`      | `AsyncConnectorClient` | Register async callback; `fn` receives `ActionsPayload`  |
| `.on_summary(fn)`      | `AsyncConnectorClient` | Register async callback; `fn` receives `SummaryPayload`  |
| `.run()`               | `Coroutine`      | Connect and process events (await this)                        |
| `.run_in_background()` | `asyncio.Task`   | Schedule `run()` as a background task; returns immediately     |
| `.stop()`              | `None`           | Signal the client to stop cleanly                              |

Supports `async with` for automatic `stop()` on exit.

---

## Reconnection behaviour

The client reconnects automatically on any network failure or non-fatal HTTP
error.  It uses exponential backoff starting at 1 s and capping at 30 s.

Fatal HTTP errors (401 Unauthorized, 403 Forbidden, 404 Not Found) are
**not** retried and will raise immediately — check your `url` and `token`.

---

## Logging and observability

The SDK uses the standard library `logging` module. It does **not** call
`logging.basicConfig()` or attach handlers — configure logging in your app
(see [Logging](docs/sdk/logging.mdx) for the full hierarchy, `extra` fields,
secrets guidance, and third-party subclass notes).

```python
import logging

logging.basicConfig(level=logging.INFO)  # your app baseline
logging.getLogger("autoplay_sdk").setLevel(logging.DEBUG)  # verbose SDK traces
```

Child loggers follow the module layout, e.g. `autoplay_sdk.chatbot`,
`autoplay_sdk.async_client`. The `autoplay_sdk.integrations` package emits **no**
log lines (constants and URL helpers only).

For counters (drops, latency, queue depth), implement **`SdkMetricsHook`**
(`autoplay_sdk.metrics`) and pass `metrics=` into the clients, summarizer, or
`RedisEventBuffer` as documented in the [Changelog](CHANGELOG.md).

---

## Compatibility

- `autoplay-sdk` currently depends on `unkey.py>=3.0.1`, which requires pydantic v2.
- Frameworks pinned to pydantic v1 (for example, Rasa 3.x stacks) cannot coexist in the same environment.
- Recommended workaround: run the SDK in a separate process and bridge to your chatbot runtime over HTTP or Redis.

---

## Self-hosted chatbot helpers

Use these when your chatbot backend is user-keyed and runs in a different process:

- **`UserSessionIndex`** (`autoplay_sdk.user_index`) — choose this when your reply endpoint receives `user_id` and you need multi-session context joins.
- **`compose_chat_pipeline(...)`** (`autoplay_sdk.chat_pipeline`) — choose this when you want safe callback wiring for summarizer + context store + agent writer in one on-actions hook.
- **`build_copilot_app(...)`** (`autoplay_sdk.serve`) — choose this when you want an out-of-the-box HTTP bridge (`/healthz`, `/context/{user_id}`, `/reply/{user_id}`, `/admin/reset/{user_id}`).

Install optional serve extras:

```bash
pip install "autoplay-sdk[serve]"
```

Reference guide: [Self-hosted chatbot bridge](docs/sdk/self-hosted-bridge.mdx).

### Self-hosted troubleshooting

1. **`/context` or `/reply` returns 404 (no activity)**
   - User has no recent indexed actions, or lookback eviction removed old sessions.
   - Verify stream ingest is active and `user_id` is present on incoming actions.

2. **User appears active but chatbot says no recent activity**
   - Identity mismatch across event source (`distinct_id`/`user_id`), widget metadata, and chatbot sender id.
   - Ensure the same user key flows end-to-end.

3. **Context missing for known sessions in multi-product setups**
   - Product-scoped retrieval requires matching `product_id`.
   - Preserve `product_id` through indexing/retrieval and pass it into context lookups.

---

## Operator onboarding (`autoplay_sdk.admin`)

**Trusted operators only** — call [`onboard_product`](autoplay_sdk/admin/onboard.py) with **`product_id`** and **`contact_email`** (plus optional URL / flags). **`POST /products`** is **open registration** (no admin header / no registration env vars on the client). **`connector_url`** defaults to **`DEFAULT_CONNECTOR_URL`** (`https://event-connector-luda.onrender.com`).

**Render**, **Unkey**, and related secrets exist **only** on the connector host — not in application code.

**v1** registers **`event_stream`** products only. The connector dual-writes Redis/Render and creates Unkey keys on **`POST /products`**. [`scripts/onboard_customer.py`](../../scripts/onboard_customer.py) still uses **`run_product_onboarding`** for CLI-style flows.

```python
from autoplay_sdk.admin import onboard_product

async def register_product_job() -> None:
    result = await onboard_product("acme-corp", contact_email="ops@yourcompany.com")
    # result.webhook_url, result.stream_url, result.webhook_secret,
    # result.unkey_key, result.unkey_key_id, …
```

Optional kwargs: **`connector_url`**, **`webhook_secret`**, **`force_reregister=True`**, **`print_operator_summary=True`**, **`key_name`**, **`connector_http_timeout_seconds`**. Lower-level **`run_product_onboarding`** (`OnboardingRunParams`) requires **`contact_email`** alongside **`product_id`**. HTTP headers apply for rare merged-config flows (no admin key for standard registration).

If the default **`connector_url`** is wrong or unreachable, registration raises **`ConnectorRegistrationHttpError`** with context instead of a bare **`httpx.ConnectError`**.

- **Re-registering the same `product_id`:** the connector returns **409** unless **`force_reregister=True`**. Catch **`ProductAlreadyRegisteredError`** if you handle 409 in code.

---

## Publishing (Test PyPI and PyPI)

You do **not** need to merge to `main` first. CI builds from the **commit the tag points to**, on whatever branch that commit lives on.

In this repo, [`.github/workflows/publish-sdk.yml`](../../../.github/workflows/publish-sdk.yml) publishes when you push a version tag:

| Tag pattern | Target |
|-------------|--------|
| `sdk-test-v0.6.8` | [Test PyPI](https://test.pypi.org/project/autoplay-sdk/) |
| `sdk-v0.6.8` | [PyPI](https://pypi.org/project/autoplay-sdk/) |

Before tagging, set the package **`version`** in [`pyproject.toml`](pyproject.toml) to the same release you intend to upload. Test PyPI rejects re-uploading an existing version.

**Trusted publishing (OIDC):** on [Test PyPI](https://test.pypi.org/) / [PyPI](https://pypi.org/) → **Publishing**, the workflow filename must be **`publish-sdk.yml`** (same as in `.github/workflows/`). A common mistake is entering **`publish-dsk.yaml`**, which produces `invalid-publisher`.

### Event connector in this monorepo

The connector always installs **`autoplay-sdk` from `src/customer_sdk`** (Dockerfile, CI, local). **`pip install autoplay-sdk`** from PyPI is for **external** applications only.

**Lockfiles:** This repo keeps **two** `uv.lock` files for reproducible installs: `/uv.lock` (connector workspace) and `./uv.lock` (the SDK package). After changing dependencies in either `pyproject.toml`, run **`uv lock`** from that same directory so the matching lockfile updates. PRs that touch both packages may legitimately change **both** lockfiles in one commit—call that out in the PR description when it happens.

---

## License

MIT
