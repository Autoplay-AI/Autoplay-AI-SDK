# Event Streaming Architecture

This document explains how real-time UI action events flow from your users' browsers to your code, and how the Python SDK is designed to handle them reliably.

---

## Overview

```
Browser (PostHog)
      │
      │  $autocapture events (HTTPS)
      ▼
Event Connector  ──────────────────────────────────────
      │   PostHog webhook receiver                    │
      │   UI action extractor                         │
      │   In-memory broadcaster (stream_store)        │
      │                                               │
      ▼                                               ▼
GET /stream/{product_id}              GET /stream/{product_id}
  SSE subscriber 1                      SSE subscriber 2
  (Python SDK)                          (Python SDK)
      │                                               │
      ▼                                               ▼
 Your callbacks                        Your callbacks
```

The connector sits between PostHog and your code. It receives raw browser interaction events, extracts structured UI actions from them, and streams those actions to any number of connected subscribers in real time.

---

## Step-by-step data flow

### 1. Browser → PostHog → Connector

PostHog captures every click, input, and navigation in the user's browser via its `$autocapture` feature. Each event is sent to a PostHog Webhook Destination pointing at:

```
POST https://<connector-host>/webhook/<product_id>
```

Each request is signed using the `webhook_secret` you registered for the product. The connector supports two signing modes in order:

1. **Plain secret** — PostHog CDP / Hog function destinations send the raw secret string in `X-PostHog-Secret`. Compared with `hmac.compare_digest` for timing safety.
2. **HMAC-SHA256** — native PostHog webhook destinations send `sha256=<hex>` in `X-PostHog-Secret`. The connector recomputes `HMAC-SHA256(key=webhook_secret, msg=body)` and compares in constant time.

On verification failure the connector returns `401`, logs `connector: invalid PostHog signature for product=<id>` at WARNING level, and increments the `signature_failures` metric counter for the product. If you see repeated `401` responses from PostHog, search connector logs for that message — it almost always means the `webhook_secret` in the connector registration does not match the secret configured in the PostHog destination.

### 2. Extraction pipeline

Once verified, the raw PostHog events pass through the connector's extraction pipeline:

```
Raw PostHog events
  → filter (drop low-signal events: $pageleave, $identify, etc.)
  → flatten (lift properties.$key → top-level key, strip $ prefix)
  → group by session_id
  → extract UI actions (map event_type → CLICK/TYPE/SUBMIT/etc.)
  → annotate with product_id, session_id, user_id, email
```

The output is a list of clean, human-readable action dicts:

```json
{
  "title": "Clicked 'Buy Now'",
  "description": "The user clicked Buy Now on the products page.",
  "canonical_url": "/products/shoes"
}
```

### 3. In-memory broadcast

The connector maintains an in-memory broadcaster (`stream_store`) keyed by `product_id`. Each connected SSE subscriber gets its own `asyncio.Queue` (max 256 items). When a batch of actions is extracted, the broadcaster fans the payload out to every queue simultaneously.

There is no Redis or disk involved in this path — delivery is purely in-memory and sub-millisecond.

### 4. SSE stream → SDK

Your Python SDK connects to:

```
GET https://<connector-host>/stream/<product_id>
Authorization: Bearer uk_live_...
```

The connection is a long-lived HTTP stream using the standard Server-Sent Events (SSE) protocol. The connector sends a `heartbeat` event every 30 seconds to keep the connection alive through proxies and load balancers.

The SDK maintains this connection, handles reconnection automatically, and dispatches events to your callbacks.

---

## SDK internal architecture

The SDK separates two concerns onto two threads so that slow callbacks never stall the stream reader:

```
┌─────────────────────────────────────────────────────┐
│  Calling thread (your main thread or a daemon)      │
│                                                     │
│  SSE receive loop                                   │
│    httpx + httpx-sse                                │
│    ↓ parse JSON                                     │
│    ↓ filter heartbeats + unknown types              │
│    ↓ put_nowait(payload)  ──────────────────────┐  │
│    ↓ if Full: dropped++, call on_drop callback  │  │
└─────────────────────────────────────────────────│──┘
                                                  │
                          queue.Queue(maxsize=500)│
                                                  │
┌─────────────────────────────────────────────────│──┐
│  Worker thread (connector-sdk-worker)           │  │
│                                                 ↓  │
│    while True:                                     │
│      payload = queue.get()                         │
│      if payload is STOP: break                     │
│      dispatch(payload) → on_actions / on_summary   │
└─────────────────────────────────────────────────────┘
```

### Why two threads?

If your `on_actions` callback writes to a database, calls an external API, or does any blocking I/O, it may take 50–500ms per event. Without the worker thread, that latency would pause the SSE receive loop — the SDK would stop reading from the stream, the server-side queue would fill up (256 items), and events would be dropped on the server before they ever reached your code.

With the worker thread, the receive loop always runs at network speed regardless of callback latency.

### Queue lifecycle

```
Event arrives        queue.put_nowait(payload)
                           │
                    queue not full? → payload queued → worker picks it up
                    queue full?     → dropped++, on_drop called, event lost
```

The queue is bounded (`max_queue_size`, default 500) to prevent unbounded memory growth if your callback is consistently slow. Monitor `client.dropped_count` — if it is non-zero, your callback needs to be faster or `max_queue_size` needs to increase.

### Sizing the queue

The right `max_queue_size` depends on your callback latency and incoming event rate. Use this formula:

```
buffer_seconds = max_queue_size / (event_rate - 1 / callback_latency_s)
```

Worked examples at 10 events/second:

| Callback latency | Queue growth rate | Time before drops at default 500 |
|---|---|---|
| 10ms | 0 items/s (callback keeps up) | Never fills |
| 50ms | 0 items/s (20 callbacks/s > 10 events/s) | Never fills |
| 100ms | +0 items/s (10 callbacks/s = 10 events/s) | Borderline — any spike causes drops |
| 200ms | +5 items/s | ~100 seconds |
| 500ms | +8 items/s | ~62 seconds |
| 1000ms | +9 items/s | ~55 seconds |

As a rule of thumb: if your callback consistently takes more than `1 / event_rate` seconds, drops will eventually occur. Either optimise the callback (e.g. batch writes, async I/O) or increase `max_queue_size` to buy more buffer time.

The server-side queue per subscriber is fixed at 256 items and covers a different scenario: the network connection between connector and SDK is slow or stalled. At 10 events/second, 256 items provides ~25 seconds of buffer before the server starts dropping for that subscriber. This is independent of your callback latency.

### Shutdown sequence

When `stop()` is called (or the `with` block exits, or `Ctrl+C` is caught):

1. `_running` is set to `False` — the receive loop exits after the current event
2. `_WORKER_STOP` sentinel is placed on the queue
3. The worker drains any remaining queued events, then exits when it sees the sentinel
4. `worker.join(timeout=10)` waits up to 10 seconds for the worker to finish

This ensures no queued events are silently discarded on shutdown.

**Timeout and mid-callback interruption.** The 10-second timeout is a hard cutoff. If the worker thread is mid-callback when the timeout expires, the daemon thread is abandoned — the callback will continue running but the main thread will no longer wait for it. In practice this matters if your callbacks write to a database or call external APIs with non-idempotent side effects. If your callbacks can take more than a few seconds, either increase the timeout by passing a longer value to `worker.join()` in your own subclass, or design callbacks to be idempotent so that a partial run on shutdown can be safely retried.

---

## Authentication

Access to the stream is protected by an Unkey API key. The key is created in the Unkey dashboard with `external_id` set to the `product_id`. The connector verifies the key on every connection — a missing, invalid, or mismatched key gets an immediate `401` response.

The SDK passes the key in the `Authorization: Bearer` header. Connections without a valid key are rejected before any events flow.

---

## What is NOT persisted

The event streaming path has no Redis, no database, and no disk writes. This means:

- Events are not replayed if the SDK is not connected when they fire
- Reconnecting picks up from the live stream, not from where you left off
- If the connector process restarts, all in-memory subscriber queues are cleared

If your use case requires durability (no missed events across restarts or deployments), the next architectural step is server-side buffering using Redis Streams, which can replay recent events on reconnect without changing your SDK code.

---

## SDK API reference

### Constructor

```python
ConnectorClient(url, token="", max_queue_size=500)
```

| Parameter | Default | Description |
|---|---|---|
| `url` | required | Full stream URL: `https://<host>/stream/<product_id>` |
| `token` | `""` | Unkey API key (`uk_live_...`) |
| `max_queue_size` | `500` | Internal queue depth before drops start |

### Builder methods (chainable)

| Method | Description |
|---|---|
| `.on_actions(fn)` | Register callback for `actions` events. `fn(payload: dict)` |
| `.on_summary(fn)` | Register callback for `summary` events. `fn(payload: dict)` |
| `.on_drop(fn)` | Register callback when an event is dropped. `fn(payload: dict, total_dropped: int)` |

### Lifecycle

| Method | Description |
|---|---|
| `.run()` | Connect and block. Reconnects on failure. |
| `.run_in_background()` | Start `run()` on a daemon thread. Returns the `Thread`. |
| `.stop()` | Signal clean shutdown. |
| `with client:` | Context manager — calls `stop()` on exit. |

### Observability

| Property | Description |
|---|---|
| `dropped_count` | Events dropped because the queue was full |
| `queue_size` | Events currently waiting in the internal queue |

---

## Event payload schemas

### `actions`

```json
{
  "type": "actions",
  "product_id": "acme_prod",
  "session_id": "ph_sess_abc123",
  "user_id": "user_456",
  "email": "alice@example.com",
  "actions": [
    {
      "title": "Clicked 'Buy Now'",
      "description": "The user clicked Buy Now on the products page.",
      "canonical_url": "/products/shoes"
    }
  ],
  "count": 1,
  "forwarded_at": 1712345678.9
}
```

`email` is omitted when PostHog has not identified the user's email. `user_id` falls back to PostHog's `distinct_id` for anonymous sessions.

### `summary`

```json
{
  "type": "summary",
  "product_id": "acme_prod",
  "session_id": "ph_sess_abc123",
  "summary": "The user browsed shoes, added a pair to their cart, and reached checkout.",
  "replaces": 12,
  "forwarded_at": 1712346000.1
}
```

Summaries are generated by an LLM when a session accumulates enough actions. They replace the raw action history with a prose description of what the user has done so far.

---

## Scaling path

| Stage | When to move | What to add |
|---|---|---|
| Worker thread (current) | Default — handles most production loads | Nothing |
| Increase `max_queue_size` | `dropped_count` climbs under load | Tune the parameter |
| Redis Streams replay | Customer cannot afford to miss events across restarts | Server-side buffer + `?since=` reconnect |
| SQS / Redis consumer groups | Multiple independent consumers of the same stream | Fan-out at the queue layer |
| Kafka | Millions of events/day, strict ordering, multiple teams | Only if truly needed |
