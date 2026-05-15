# SSE Integration

You open a single long-lived HTTP connection to the connector and events are pushed to you as they happen. No polling, no endpoint to expose.

---

## Connection

```
GET https://<connector-host>/stream/<product_id>
Authorization: Bearer <webhook_secret>
Accept: text/event-stream
```

The connection stays open indefinitely. Each event arrives as an SSE message on the wire:

```
data: {"type":"actions","product_id":"acme_prod","session_id":"ph_sess_abc123","actions":[...],"count":1,"forwarded_at":1712345678.9}

data: {"type":"summary","product_id":"acme_prod","session_id":"ph_sess_abc123","summary":"...","replaces":12,"forwarded_at":1712346000.1}
```

---

## Heartbeat

Every 30 seconds the connector sends a named keep-alive event to prevent proxies and load balancers from closing idle connections:

```
event: heartbeat
data:
```

Your client should ignore events with `event: heartbeat`.

---

## Reconnection

SSE connections can drop (network blip, server restart, etc.). Always reconnect with exponential backoff:

| Attempt | Wait before retry |
|---------|-------------------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |
| 4 | 8 seconds |
| 5+ | 30 seconds (cap) |

> The connector does not currently support `Last-Event-ID` resumption — events delivered while disconnected are not replayed. If guaranteed delivery is critical, use the [Push](../push/README.md) mode instead.

---

## Auth errors

| Status | Meaning |
|--------|---------|
| `401` | Missing or invalid Bearer token |
| `404` | Product not registered |
| `400` | Product is not in `event_stream` / `sse` mode |

These are returned immediately before the SSE stream begins.

---

## Reference implementations

- **Python** — [`client_example.py`](./client_example.py) uses `httpx-sse` with auto-reconnect
- **JavaScript (browser + Node.js)** — [`client_example.js`](./client_example.js) uses the native `EventSource` API

```bash
# Python
pip install httpx httpx-sse
python client_example.py

# Node.js
npm install eventsource
node client_example.js
```
