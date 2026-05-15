# Event Connector — Integration Guide

This guide helps you choose the right delivery mode and get up and running quickly.

The connector extracts structured UI actions from your users' browser sessions and delivers them to your code in real-time. You receive clean, human-readable events like:

```
"User clicked 'Buy Now' on /products/shoes"
"User navigated to /checkout/payment"
```

---

## Choose your delivery mode

| | **Push (Webhook)** | **SSE** | **SDK** |
|---|---|---|---|
| **How it works** | We POST events to your endpoint | You open a long-lived HTTP connection; we stream events to you | Thin Python wrapper around SSE |
| **Your infra needed** | A public HTTP endpoint | Any server that can keep an HTTP connection open | Same as SSE |
| **Real-time latency** | < 1 second | < 1 second | < 1 second |
| **Language support** | Any (just receive POST) | Any (standard EventSource / SSE) | Python only |
| **Retry on failure** | Yes — automatic exponential backoff | No — reconnect and resume | Auto-reconnect built in |
| **Auth** | HMAC-SHA256 signature on each request | Bearer token on connect | Bearer token passed to SDK |
| **Ideal for** | Existing backends, serverless functions, most integrations | Browser clients, long-running servers, fan-out to multiple consumers | Python scripts, prototypes, background workers |

### Decision guide

- **You have an existing web server or API** → use **Push**. You only need one route that accepts POST.
- **You are building a browser app or a long-lived server process** → use **SSE**. You connect once and events arrive as they happen.
- **You are writing a Python script or background worker** → use the **SDK**. It wraps SSE behind a three-line callback interface.
- **You need automatic retry of missed events** → use **Push**. The connector retries failed deliveries up to `MAX_RETRIES` times with exponential backoff.

---

## Event payload schema

All three modes deliver the same JSON payload. Understanding it once is enough.

### `actions` event

Fired whenever the connector extracts UI actions from a user session.

```json
{
  "type": "actions",
  "product_id": "acme_prod",
  "session_id": "ph_sess_abc123",
  "actions": [
    {
      "title": "Clicked 'Buy Now'",
      "description": "User clicked the purchase button on the product page",
      "canonical_url": "/products/shoes"
    }
  ],
  "count": 1,
  "forwarded_at": 1712345678.9
}
```

| Field | Type | Description |
|---|---|---|
| `type` | `"actions"` | Always `"actions"` for this event type |
| `product_id` | string | Your product identifier as registered |
| `session_id` | string \| null | PostHog session identifier for this user |
| `actions` | array | Ordered list of extracted UI actions |
| `actions[].title` | string | Short label for the action (e.g. `"Clicked 'Buy Now'"`) |
| `actions[].description` | string | Human-readable description of what the user did |
| `actions[].canonical_url` | string | Normalised URL path where the action occurred |
| `count` | integer | Number of actions in this batch |
| `forwarded_at` | float | Unix timestamp (seconds) when this batch was forwarded |

### `summary` event

Fired when LLM summarisation is enabled and enough actions have accumulated. Replaces the raw action history with a prose summary.

```json
{
  "type": "summary",
  "product_id": "acme_prod",
  "session_id": "ph_sess_abc123",
  "summary": "The user browsed shoes, added a pair to their cart, and reached the payment page before dropping off.",
  "replaces": 12,
  "forwarded_at": 1712346000.1
}
```

| Field | Type | Description |
|---|---|---|
| `type` | `"summary"` | Always `"summary"` for this event type |
| `product_id` | string | Your product identifier |
| `session_id` | string \| null | PostHog session identifier |
| `summary` | string | LLM-generated prose summary of the session so far |
| `replaces` | integer | Number of raw action events this summary replaces |
| `forwarded_at` | float | Unix timestamp when the summary was forwarded |

---

## Setup

### 1. Register your product

Send a `POST /products` request to the connector with your chosen delivery mode.

**Push mode:**

```bash
curl -X POST https://<connector-host>/products \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "acme_prod",
    "contact_email": "you@yourcompany.com",
    "webhook_secret": "your-posthog-secret",
    "integration_type": "event_stream",
    "integration_config": {
      "mode": "push",
      "url": "https://your-server.example.com/events",
      "secret": "your-bearer-token"
    }
  }'
```

**SSE mode:**

```bash
curl -X POST https://<connector-host>/products \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "acme_prod",
    "contact_email": "you@yourcompany.com",
    "webhook_secret": "your-posthog-secret",
    "integration_type": "event_stream",
    "integration_config": {
      "mode": "sse"
    }
  }'
```

> `webhook_secret` is the secret you configured in PostHog to sign inbound events. `secret` inside `integration_config` is the token the connector will send to **your** endpoint in the `Authorization: Bearer` header.

### 2. Point PostHog at the connector

In your PostHog project, create a Webhook Destination pointing to:

```
POST https://<connector-host>/webhook/acme_prod
```

Set the signing secret to match the `webhook_secret` you registered.

### 3. Receive events

Follow the guide for your chosen mode:

- [Push (Webhook)](./push/README.md)
- [SSE](./sse/README.md)
- [Python SDK](./sdk/README.md)

---

## Security

### Push — verifying the signature

Every push request includes an `X-Connector-Signature` header containing an HMAC-SHA256 digest of the request body, keyed with your `secret`:

```
X-Connector-Signature: sha256=<hex-digest>
```

Always verify this header before processing the payload. See [push/README.md](./push/README.md) for the verification steps and reference code.

### SSE — Bearer token

Connect with the `Authorization: Bearer <secret>` header. The token is checked against the `webhook_secret` you registered for the product. Connections without a valid token receive a `401` response immediately.

---

## Versioning

The payload schema is currently at **v1**. Future breaking changes will be announced with a version bump in this document and communicated before rollout.

Non-breaking additions (new optional fields) may be added at any time — your code should ignore unknown fields.
