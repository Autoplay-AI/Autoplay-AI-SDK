# Push (Webhook) Integration

The connector POSTs JSON events to an HTTP endpoint you own. This is the simplest integration pattern — you just need one route that accepts `POST` requests.

---

## What you need to build

A public HTTPS endpoint that:

1. Accepts `POST` requests with `Content-Type: application/json`
2. Reads and verifies the `X-Connector-Signature` header
3. Processes the JSON body
4. Returns `HTTP 200` to acknowledge receipt

Any other status code (or a timeout) is treated as a failure and the connector will retry.

---

## Request format

```
POST https://your-server.example.com/events
Content-Type: application/json
Authorization: Bearer <your-secret>
X-Connector-Signature: sha256=<hmac-hex>
```

Body — see the full payload schema in [INTEGRATION.md](../INTEGRATION.md).

---

## Signature verification

Every request includes an `X-Connector-Signature` header:

```
X-Connector-Signature: sha256=<hex-digest>
```

The digest is computed as `HMAC-SHA256(key=your_secret, message=raw_request_body)`.

**Always verify this before processing.** Reject requests that fail verification with `HTTP 401`.

```python
import hashlib
import hmac

def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
```

> Use `hmac.compare_digest` — not `==` — to prevent timing attacks.

---

## Retry behaviour

If your endpoint returns anything other than `2xx`, or if the request times out, the connector queues the batch for retry:

| Attempt | Delay |
|---------|-------|
| 1 (initial) | immediate |
| 2 | ~2 seconds |
| 3 | ~4 seconds |
| … | exponential backoff |
| Max (`MAX_RETRIES`) | batch dropped and logged |

Your endpoint must be **idempotent** — the same batch may arrive more than once during retries.

---

## Response codes

| Code | Meaning |
|------|---------|
| `200` | Accepted — processing can be async |
| `4xx` | Client error — batch will NOT be retried |
| `5xx` | Server error — batch will be retried |
| Timeout | Network error — batch will be retried |

---

## Reference implementation

See [`receiver_example.py`](./receiver_example.py) for a minimal FastAPI server you can copy-paste and adapt.

```bash
pip install fastapi uvicorn
python receiver_example.py
# Listens on http://localhost:8000/events
```
