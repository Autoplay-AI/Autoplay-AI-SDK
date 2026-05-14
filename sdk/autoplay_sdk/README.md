# autoplay-sdk

Real-time event streaming client for Autoplay connectors.

Receives structured UI actions and LLM session summaries from the Autoplay
event connector as they happen, then routes them into your RAG pipeline,
vector store, or agent context — with zero added latency on the hot path.

---

## Installation

```bash
pip install autoplay-sdk
```

**Python:** 3.10 or later required.

**Changelog:** see [CHANGELOG.md](../CHANGELOG.md) for version history.

**Migrating from 0.2.x?** Version 0.4.0 introduced `LazyRedisClient` — the
module-level `_redis_client` / `_redis_available` attributes no longer exist
on storage modules. See the [Breaking changes](../CHANGELOG.md) section for
details.

---

## Architecture

```
Autoplay connector
       │
       │  SSE stream (HTTP/1.1 long-lived GET)
       │  or webhook POSTs
       ▼
┌─────────────────────┐
│  ConnectorClient    │  sync — dedicated reader thread + worker thread
│  AsyncConnectorClient│ async — asyncio SSE loop + per-session semaphore
│  WebhookReceiver    │  push mode — verify + parse + dispatch
└─────────────────────┘
       │
       │  typed ActionsPayload / SummaryPayload
       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Your callbacks                           │
│  EventBuffer        — pull later (dev/low-traffic)          │
│  RedisEventBuffer   — durable sliding window (production)   │
│  SessionSummarizer  — rolling LLM summary per session       │
│  ContextStore       — enrich(session_id, query) at query time│
│  RagPipeline        — embed + upsert on every event         │
│  AsyncAgentContextWriter — push context to an agent dest.   │
└─────────────────────────────────────────────────────────────┘
```

### What is on the hot path

The **hot path** is the code that runs between receiving a byte on the network
and returning control to the SSE reader loop.  Nothing user-visible lives on it:

- **`ConnectorClient`** — the reader thread enqueues the raw parsed dict into a
  `queue.Queue` and immediately loops back to the stream.  All your callbacks
  run on a *separate* worker thread.
- **`AsyncConnectorClient`** — `_handle` parses the SSE frame and calls
  `_dispatch`, which acquires a per-session semaphore and then `await`s your
  callback.  The semaphore means slow callbacks for session A never delay
  session B, but *within a session* the callback runs before the next event for
  that session is dispatched.

**Callbacks are not on the hot path.**  Write them as freely as you need to.

---

## Choosing between sync and async

| Question | Use |
|----------|-----|
| My app already uses `asyncio` (FastAPI, LlamaIndex, LangChain) | `AsyncConnectorClient` |
| I need to `await` embedding APIs or vector stores in my callback | `AsyncConnectorClient` |
| I'm writing a simple script or CLI tool | `ConnectorClient` |
| My callbacks are plain synchronous functions with no I/O | `ConnectorClient` |
| I receive events via webhook (push mode) | `WebhookReceiver` |

> **Warning — sync callbacks in `AsyncConnectorClient`**
>
> `AsyncConnectorClient` accepts plain `def` callbacks for convenience, but a
> sync callback that blocks (e.g. a synchronous DB write, `requests.post`) will
> stall the entire event loop during dispatch.  Always use `async def` for any
> I/O.  If you must call blocking code, wrap it:
>
> ```python
> async def on_actions(payload):
>     await asyncio.to_thread(blocking_sync_function, payload)
> ```

---

## Component map

| Class | One-line purpose |
|-------|-----------------|
| `ConnectorClient` | Sync SSE client; reader thread + worker thread; safe for blocking callbacks |
| `AsyncConnectorClient` | Async SSE client; per-session semaphore isolation; use `async def` callbacks |
| `WebhookReceiver` | Push mode; HMAC verification + typed dispatch for webhook POSTs |
| `ActionsPayload` | Typed model for a batch of UI actions from one session |
| `SummaryPayload` | Typed model for an LLM-generated session summary |
| `EventBuffer` | In-memory pull buffer; thread-safe; use for dev/testing |
| `RedisEventBuffer` | Redis-backed sliding-window buffer; async; use in production |
| `BufferBackend` | Protocol — implement to plug in Kafka, Postgres, etc. |
| `SessionSummarizer` | Sync rolling LLM summarizer; compact context window per session |
| `AsyncSessionSummarizer` | Async version with per-session worker tasks; ordered guarantee |
| `ContextStore` | Sync store; call `enrich(session_id, query)` at query time |
| `AsyncContextStore` | Async write side; sync `enrich()` safe to call from any coroutine |
| `RagPipeline` | Sync embed + upsert wired directly to client callbacks |
| `AsyncRagPipeline` | Async embed + upsert; awaits your embedding and vector store calls |
| `AsyncAgentContextWriter` | Push raw actions to a destination; overwrite with LLM summary |
| `SdkMetricsHook` | Protocol — implement to receive Prometheus/Datadog/OTEL counters |

---

## Quickstart

### Sync (scripts, CLI tools)

```python
from autoplay_sdk import ConnectorClient, ActionsPayload

def on_actions(payload: ActionsPayload) -> None:
    text = payload.to_text()          # embedding-ready string
    embed_and_upsert(text, payload.session_id)

ConnectorClient(url="https://host/stream/my_product", token="uk_live_...") \
    .on_actions(on_actions) \
    .run()
```

### Async (FastAPI, LangChain, LlamaIndex)

```python
import asyncio
from autoplay_sdk import AsyncConnectorClient, ActionsPayload

async def on_actions(payload: ActionsPayload) -> None:
    vector = await embed(payload.to_text())
    await vector_store.upsert(payload.session_id, vector)

async def main():
    async with AsyncConnectorClient(url="...", token="...") as client:
        client.on_actions(on_actions)
        await client.run()

asyncio.run(main())
```

### Push webhook (any HTTP framework)

```python
from autoplay_sdk import WebhookReceiver

receiver = WebhookReceiver(secret="...", on_actions=handle_actions)

# FastAPI
@app.post("/events")
async def events(request: Request, x_connector_signature: str | None = Header(None)):
    await receiver.handle(await request.body(), x_connector_signature)
    return {"status": "ok"}
```

---

## Performance and locking

| Component | Lock type | Why |
|-----------|-----------|-----|
| `ConnectorClient` | `queue.Queue` | Decouples reader from callbacks; never blocks the reader |
| `EventBuffer` | `threading.Lock` | Short critical section; just a deque append/pop |
| `SessionSummarizer` | `threading.Lock` | Short critical section; just a list append and integer increment |
| `AsyncSessionSummarizer` | `asyncio.Lock` | Per-session worker tasks; no threads; lock is never held during I/O |
| `ContextStore` | `threading.Lock` | Short critical section; safe from any coroutine |
| `AsyncContextStore` | `threading.Lock` | Intentional — same short critical section, no I/O inside the lock |
| `AsyncConnectorClient` | `asyncio.Semaphore` per session | Limits concurrent in-flight callbacks per session |
| `RedisEventBuffer` | `asyncio.Semaphore` | Backpressure; drops rather than queuing unboundedly |

`AsyncContextStore` uses a `threading.Lock` (not an `asyncio.Lock`) because the
critical section contains only in-memory dict mutations — no `await` or I/O.
Holding a `threading.Lock` for a few microseconds is imperceptible to the event
loop.  Replacing it with an `asyncio.Lock` would add overhead without benefit.

---

## Reconnect policy

Both `ConnectorClient` and `AsyncConnectorClient` reconnect automatically:

- First retry after `initial_backoff_s` (default 1 s).
- Each retry doubles the wait, capped at `max_backoff_s` (default 30 s).
- ±10 % random jitter is added to spread thundering-herd reconnects.
- HTTP 401, 403, 404 are immediately fatal — check your URL and token.
- Set `max_retries=N` to limit attempts; `None` (default) retries forever.

---

## Metrics

Implement `SdkMetricsHook` to receive internal counters:

```python
from autoplay_sdk import ConnectorClient
from autoplay_sdk.metrics import SdkMetricsHook

class MyMetrics:
    def record_event_dropped(self, *, reason, event_type, session_id, product_id):
        counter.inc()

    def record_queue_depth(self, *, depth):
        gauge.set(depth)

client = ConnectorClient(url=URL, token=TOKEN, metrics=MyMetrics())
```

See [`metrics.py`](metrics.py) for all available hook methods and which are
currently wired vs. reserved for future use.
