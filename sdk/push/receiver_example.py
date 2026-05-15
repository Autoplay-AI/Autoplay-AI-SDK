"""Push webhook receiver example.

Copy-paste this file into your project, set CONNECTOR_SECRET, and run:

    pip install fastapi uvicorn
    CONNECTOR_SECRET=your-secret uvicorn receiver_example:app --port 8000

The connector will POST events to http://your-host:8000/events.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Connector Event Receiver Example")

# Set this to the `secret` value you configured in integration_config.
CONNECTOR_SECRET: str = os.getenv("CONNECTOR_SECRET", "")


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Return True if the HMAC-SHA256 signature is valid.

    The connector signs requests with:
        HMAC-SHA256(key=CONNECTOR_SECRET, message=raw_body)

    and sends the result as:
        X-Connector-Signature: sha256=<hex-digest>
    """
    if not CONNECTOR_SECRET:
        # No secret configured — accept all (not recommended in production).
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(CONNECTOR_SECRET.encode(), body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# Event handlers — replace these with your own logic
# ---------------------------------------------------------------------------


def handle_actions(payload: dict) -> None:
    """Called for every 'actions' event.

    payload fields:
        product_id    str        — your product identifier
        session_id    str|None   — PostHog session id
        actions       list[dict] — [{title, description, canonical_url}, ...]
        count         int        — len(actions)
        forwarded_at  float      — Unix timestamp
    """
    logger.info(
        "product=%s session=%s received %d action(s)",
        payload.get("product_id"),
        payload.get("session_id"),
        payload.get("count", 0),
    )
    for action in payload.get("actions", []):
        logger.info(
            "  %s — %s (%s)",
            action["title"],
            action["description"],
            action["canonical_url"],
        )


def handle_summary(payload: dict) -> None:
    """Called for every 'summary' event (requires SUMMARY_ENABLED on the connector).

    payload fields:
        product_id    str        — your product identifier
        session_id    str|None   — PostHog session id
        summary       str        — prose summary of the session
        replaces      int        — number of raw action entries this replaces
        forwarded_at  float      — Unix timestamp
    """
    logger.info(
        "product=%s session=%s summary (replaces %d): %s",
        payload.get("product_id"),
        payload.get("session_id"),
        payload.get("replaces", 0),
        payload.get("summary", ""),
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@app.post("/events")
async def receive_events(
    request: Request,
    x_connector_signature: str | None = Header(default=None),
):
    """Receive and process events from the connector."""
    body = await request.body()

    if not _verify_signature(body, x_connector_signature):
        logger.warning("Invalid signature — rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = payload.get("type")

    if event_type == "actions":
        handle_actions(payload)
    elif event_type == "summary":
        handle_summary(payload)
    else:
        logger.warning("Unknown event type: %s", event_type)

    # Return 200 immediately — processing can be async / queued.
    return JSONResponse(content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
