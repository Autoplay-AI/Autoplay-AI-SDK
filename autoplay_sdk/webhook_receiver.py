"""autoplay_sdk.webhook_receiver — Typed push webhook receiver.

Drop-in replacement for the ``push/receiver_example.py`` copy-paste pattern.
Gives push-mode customers the same typed ``ActionsPayload`` / ``SummaryPayload``
interface that SSE users get from ``AsyncConnectorClient``.

How push mode works
-------------------
When a product is configured with ``integration_type: event_stream`` and a
``forward_url``, the connector POSTs events to that URL as JSON:

    POST /your-endpoint
    X-Connector-Signature: sha256=<hmac-hex>
    Content-Type: application/json

    {"type": "actions", "product_id": "...", "session_id": "...", ...}

``WebhookReceiver`` handles signature verification, JSON parsing, and
dispatching to typed callbacks — everything the copy-paste example does
manually, in one reusable class.

Usage (FastAPI)::

    import os
    from fastapi import FastAPI, Header, HTTPException, Request
    from autoplay_sdk import WebhookReceiver, ActionsPayload, SummaryPayload

    async def handle_actions(payload: ActionsPayload) -> None:
        for action in payload.actions:
            print(action.title, action.description)

    async def handle_summary(payload: SummaryPayload) -> None:
        print(payload.summary)

    receiver = WebhookReceiver(
        secret=os.getenv("CONNECTOR_SECRET", ""),
        on_actions=handle_actions,
        on_summary=handle_summary,
    )

    @app.post("/events")
    async def events(
        request: Request,
        x_connector_signature: str | None = Header(default=None),
    ):
        body = await request.body()
        try:
            await receiver.handle(body, x_connector_signature)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        return {"status": "ok"}

Usage (Flask / sync)::

    from flask import Flask, request, abort
    from autoplay_sdk import WebhookReceiver

    receiver = WebhookReceiver(secret="...", on_actions=handle_actions)

    @app.post("/events")
    def events():
        body = request.get_data()
        sig  = request.headers.get("X-Connector-Signature")
        try:
            receiver.handle_sync(body, sig)
        except ValueError:
            abort(401)
        return {"status": "ok"}

Signature verification
----------------------
The connector signs every POST with HMAC-SHA256::

    X-Connector-Signature: sha256=<hex-digest>

where ``hex-digest = HMAC-SHA256(key=secret, message=raw_body)``.
``WebhookReceiver.verify()`` replicates this check using
``hmac.compare_digest`` to prevent timing attacks.  If no secret is
configured (empty string), all requests are accepted — useful in development
but not recommended in production.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from typing import Any

from autoplay_sdk.models import ActionsPayload, AnyPayload, SummaryPayload

logger = logging.getLogger(__name__)

ActionCallback = Callable[[ActionsPayload], Any]
SummaryCallback = Callable[[SummaryPayload], Any]


class WebhookReceiver:
    """Typed push webhook receiver — HMAC verification + typed payload parsing.

    Parses incoming connector webhook POSTs into typed ``ActionsPayload`` /
    ``SummaryPayload`` objects and dispatches them to registered callbacks.
    Supports both sync and async callbacks transparently.

    Args:
        secret:      HMAC-SHA256 signing secret configured on the connector
                     (``integration_config.secret``).  Pass an empty string to
                     skip verification (development only).
        on_actions:  Sync or async ``(payload: ActionsPayload) -> None`` called
                     for every ``actions`` event.
        on_summary:  Sync or async ``(payload: SummaryPayload) -> None`` called
                     for every ``summary`` event.

    Example::

        receiver = WebhookReceiver(
            secret=os.getenv("CONNECTOR_SECRET", ""),
            on_actions=handle_actions,
            on_summary=handle_summary,
        )
    """

    def __init__(
        self,
        secret: str = "",
        on_actions: ActionCallback | None = None,
        on_summary: SummaryCallback | None = None,
    ) -> None:
        self._secret = secret
        self._on_actions = on_actions
        self._on_summary = on_summary

    # ------------------------------------------------------------------
    # Builder interface
    # ------------------------------------------------------------------

    def on_actions(self, fn: ActionCallback) -> "WebhookReceiver":
        """Register a callback for ``actions`` events.

        Args:
            fn: Sync or async ``(payload: ActionsPayload) -> None``.

        Returns:
            self — for method chaining.
        """
        self._on_actions = fn
        return self

    def on_summary(self, fn: SummaryCallback) -> "WebhookReceiver":
        """Register a callback for ``summary`` events.

        Args:
            fn: Sync or async ``(payload: SummaryPayload) -> None``.

        Returns:
            self — for method chaining.
        """
        self._on_summary = fn
        return self

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def verify(self, body: bytes, signature_header: str | None) -> bool:
        """Return ``True`` if the HMAC-SHA256 signature is valid.

        The connector signs every POST with::

            X-Connector-Signature: sha256=<HMAC-SHA256(key=secret, msg=body)>

        If no ``secret`` was configured (empty string), all requests are
        accepted — useful in development but not recommended in production.

        Args:
            body:             Raw request body bytes.
            signature_header: Value of the ``X-Connector-Signature`` header.

        Returns:
            ``True`` if the signature is valid or no secret is configured.
            ``False`` if the header is missing, malformed, or the digest
            does not match.
        """
        if not self._secret:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()
        received = signature_header.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)

    def parse(self, body: bytes) -> AnyPayload | None:
        """Parse raw request body bytes into a typed payload object.

        Args:
            body: Raw JSON request body.

        Returns:
            ``ActionsPayload`` or ``SummaryPayload`` instance, or ``None``
            if the body cannot be parsed or the event type is unrecognised.
        """
        try:
            raw = json.loads(body)
        except json.JSONDecodeError:
            logger.warning(
                "autoplay_sdk: WebhookReceiver could not parse JSON body",
                exc_info=True,
            )
            return None

        event_type = raw.get("type")
        try:
            if event_type == "actions":
                return ActionsPayload.from_dict(raw)
            if event_type == "summary":
                return SummaryPayload.from_dict(raw)
        except Exception as exc:
            logger.warning(
                "autoplay_sdk: WebhookReceiver failed to deserialize event_type=%s — skipping: %s",
                event_type,
                exc,
                exc_info=True,
                extra={"event_type": event_type},
            )
            return None

        logger.debug(
            "autoplay_sdk: WebhookReceiver unknown event type: %s",
            event_type,
            extra={"event_type": event_type},
        )
        return None

    async def handle(
        self,
        body: bytes,
        signature_header: str | None = None,
    ) -> AnyPayload | None:
        """Verify, parse, and dispatch a webhook POST — async version.

        Verifies the HMAC signature, parses the body into a typed payload,
        and calls the registered ``on_actions`` or ``on_summary`` callback.
        Both sync and async callbacks are supported.

        Args:
            body:             Raw request body bytes.
            signature_header: Value of the ``X-Connector-Signature`` header.

        Returns:
            The parsed ``ActionsPayload`` or ``SummaryPayload``, or ``None``
            if the body was unrecognisable.

        Raises:
            ValueError: If the HMAC signature is invalid.

        Example::

            body = await request.body()
            sig  = request.headers.get("X-Connector-Signature")
            payload = await receiver.handle(body, sig)
        """
        if not self.verify(body, signature_header):
            logger.warning(
                "autoplay_sdk: WebhookReceiver rejected request — invalid signature",
            )
            raise ValueError("Invalid X-Connector-Signature")

        payload = self.parse(body)
        if payload is None:
            return None

        cb: ActionCallback | SummaryCallback | None
        event_type = "actions" if isinstance(payload, ActionsPayload) else "summary"
        if isinstance(payload, ActionsPayload):
            cb = self._on_actions
        else:
            cb = self._on_summary

        if cb is not None:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: WebhookReceiver callback raised for event_type=%s session=%s: %s",
                    event_type,
                    payload.session_id,
                    exc,
                    exc_info=True,
                    extra={
                        "event_type": event_type,
                        "session_id": payload.session_id,
                        "product_id": payload.product_id,
                    },
                )

        return payload

    def handle_sync(
        self,
        body: bytes,
        signature_header: str | None = None,
    ) -> AnyPayload | None:
        """Verify, parse, and dispatch a webhook POST — sync version.

        Same as ``handle()`` but for synchronous frameworks (Flask, Django,
        etc.).  Callbacks must be synchronous when using this method.

        Args:
            body:             Raw request body bytes.
            signature_header: Value of the ``X-Connector-Signature`` header.

        Returns:
            The parsed ``ActionsPayload`` or ``SummaryPayload``, or ``None``
            if the body was unrecognisable.

        Raises:
            ValueError: If the HMAC signature is invalid.
            TypeError: If an async callback is registered — use ``handle``
                instead, which is a coroutine and awaits async callbacks.

        Example::

            body = request.get_data()
            sig  = request.headers.get("X-Connector-Signature")
            payload = receiver.handle_sync(body, sig)
        """
        if not self.verify(body, signature_header):
            logger.warning(
                "autoplay_sdk: WebhookReceiver rejected request — invalid signature",
            )
            raise ValueError("Invalid X-Connector-Signature")

        payload = self.parse(body)
        if payload is None:
            return None

        cb: ActionCallback | SummaryCallback | None
        event_type = "actions" if isinstance(payload, ActionsPayload) else "summary"
        if isinstance(payload, ActionsPayload):
            cb = self._on_actions
        else:
            cb = self._on_summary

        if cb is not None:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    result.close()  # prevent ResourceWarning
                    raise TypeError(
                        f"handle_sync does not support async callbacks; "
                        f"use handle() instead. Got coroutine from {cb!r}"
                    )
            except Exception as exc:
                logger.error(
                    "autoplay_sdk: WebhookReceiver callback raised for event_type=%s session=%s: %s",
                    event_type,
                    payload.session_id,
                    exc,
                    exc_info=True,
                    extra={
                        "event_type": event_type,
                        "session_id": payload.session_id,
                        "product_id": payload.product_id,
                    },
                )

        return payload

    def __repr__(self) -> str:
        has_secret = bool(self._secret)
        return (
            f"WebhookReceiver("
            f"secret={'set' if has_secret else 'unset'}, "
            f"on_actions={self._on_actions is not None}, "
            f"on_summary={self._on_summary is not None})"
        )
