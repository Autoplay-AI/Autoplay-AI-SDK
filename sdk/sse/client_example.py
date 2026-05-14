"""SSE client example — Python.

Connects to the connector's SSE endpoint and prints events as they arrive.
Reconnects automatically with exponential backoff on any connection failure.

Usage:
    pip install httpx httpx-sse
    CONNECTOR_URL=https://<host>/stream/acme_prod CONNECTOR_TOKEN=tok_xyz python client_example.py
"""

from __future__ import annotations

import json
import logging
import os
import time

import httpx
from httpx_sse import connect_sse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CONNECTOR_URL: str = os.getenv(
    "CONNECTOR_URL", "http://localhost:8080/stream/acme_prod"
)
CONNECTOR_TOKEN: str = os.getenv("CONNECTOR_TOKEN", "")

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0


# ---------------------------------------------------------------------------
# Event handlers — replace these with your own logic
# ---------------------------------------------------------------------------


def on_actions(payload: dict) -> None:
    """Called for every 'actions' event."""
    logger.info(
        "product=%s session=%s — %d action(s):",
        payload.get("product_id"),
        payload.get("session_id"),
        payload.get("count", 0),
    )
    for action in payload.get("actions", []):
        logger.info("  [%s] %s", action["canonical_url"], action["title"])


def on_summary(payload: dict) -> None:
    """Called for every 'summary' event."""
    logger.info(
        "product=%s session=%s — summary (replaces %d): %s",
        payload.get("product_id"),
        payload.get("session_id"),
        payload.get("replaces", 0),
        payload.get("summary", ""),
    )


# ---------------------------------------------------------------------------
# SSE consumer with reconnection
# ---------------------------------------------------------------------------


def _process_event(event) -> None:
    """Dispatch a single SSE event to the appropriate handler."""
    if event.event == "heartbeat":
        return  # keep-alive — ignore

    try:
        payload = json.loads(event.data)
    except json.JSONDecodeError:
        logger.warning("Could not parse event data: %s", event.data[:200])
        return

    event_type = payload.get("type")
    if event_type == "actions":
        on_actions(payload)
    elif event_type == "summary":
        on_summary(payload)
    else:
        logger.debug("Unknown event type: %s", event_type)


def listen() -> None:
    """Connect to the SSE endpoint and consume events, reconnecting on failure."""
    headers = {"Accept": "text/event-stream"}
    if CONNECTOR_TOKEN:
        headers["Authorization"] = f"Bearer {CONNECTOR_TOKEN}"

    backoff = _BACKOFF_INITIAL

    while True:
        try:
            logger.info("Connecting to %s", CONNECTOR_URL)
            with httpx.Client(timeout=None) as client:
                with connect_sse(
                    client, "GET", CONNECTOR_URL, headers=headers
                ) as event_source:
                    logger.info("Connected — waiting for events")
                    backoff = _BACKOFF_INITIAL  # reset on successful connection
                    for sse in event_source.iter_sse():
                        _process_event(sse)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403, 404):
                logger.error(
                    "Fatal error %d — check your URL and token",
                    exc.response.status_code,
                )
                raise
            logger.warning(
                "HTTP %d — will retry in %.0fs", exc.response.status_code, backoff
            )

        except Exception as exc:
            logger.warning("Connection lost (%s) — will retry in %.0fs", exc, backoff)

        time.sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_MAX)


if __name__ == "__main__":
    listen()
