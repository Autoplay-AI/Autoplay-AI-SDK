"""HTTP helpers for ``POST /products`` (onboarding client, not the API server).

Raised errors are catchable in tests; calling CLIs typically map them to stderr
and ``sys.exit``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from autoplay_sdk.admin.onboarding_constants import (
    onboard_connector_http_timeout_seconds,
)

_REDACT_PLACEHOLDER = "[REDACTED]"
# Lowercase key names whose JSON values are replaced (any nesting depth).
_SENSITIVE_JSON_KEYS: frozenset[str] = frozenset(
    {
        "webhook_secret",
        "forward_secret",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "password",
        "secret",
        "x_posthog_secret",
    }
)
# Non-JSON error bodies longer than this are replaced with a length-only placeholder.
_MAX_PLAINTEXT_ERROR_BODY: int = 4096


def _connector_transport_user_message(
    connector_url: str, exc: httpx.RequestError
) -> str:
    """Human-oriented message when the admin POST never receives an HTTP response."""
    detail = str(exc).strip() or type(exc).__name__
    base = (connector_url or "").strip().rstrip("/") or "(empty CONNECTOR_URL)"
    return (
        f"Could not reach the connector at {base!r} ({detail}). "
        "Check the connector_url you passed to onboard_product (deployed event connector "
        "base URL). Render and Unkey credentials belong on the connector host only."
    )


def redact_connector_error_response_text(text: str) -> str:
    """Redact likely secrets in connector error bodies before logging or attaching to exceptions.

    Parses JSON when possible and replaces values for known sensitive keys at any depth.
    Non-JSON bodies are passed through if short; very long bodies are omitted to reduce leak risk.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        if len(raw) > _MAX_PLAINTEXT_ERROR_BODY:
            return f"<non-JSON response omitted ({len(raw)} chars)>"
        return raw
    return json.dumps(_redact_json_value(parsed), separators=(",", ":"))


def _redact_json_value(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in _SENSITIVE_JSON_KEYS:
                if v in (None, "", [], {}):
                    out[k] = v
                else:
                    out[k] = _REDACT_PLACEHOLDER
            else:
                out[k] = _redact_json_value(v)
        return out
    if isinstance(obj, list):
        return [_redact_json_value(x) for x in obj]
    return obj


class ConnectorRegistrationHttpError(Exception):
    """Non-201 or validation failure when calling the connector admin API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class ProductAlreadyRegisteredError(ConnectorRegistrationHttpError):
    """Connector returned HTTP 409 — product_id exists; use force_reregister to overwrite."""


def _registration_tty_ui() -> bool:
    """True when stdout is a TTY (interactive terminal); suppress spinner in CI / pipes."""
    return sys.stdout.isatty()


def build_register_payload_from_cli(
    *,
    product_id: str,
    contact_email: str,
    webhook_secret: str,
    integration_type: str,
    forward_url: str,
    forward_secret: str,
) -> dict[str, Any]:
    """JSON body for first onboard ``POST /products`` (CLI-derived integration_config)."""
    integration_config: dict[str, Any] = {}
    if integration_type == "event_stream":
        integration_config = {"mode": "sse"}
    elif integration_type == "webhook" and forward_url:
        integration_config = {"url": forward_url, "secret": forward_secret}
    return {
        "product_id": product_id,
        "contact_email": contact_email,
        "webhook_secret": webhook_secret,
        "integration_type": integration_type,
        "integration_config": integration_config,
        "forward_url": forward_url,
        "forward_secret": forward_secret,
    }


def build_register_payload_from_merged_entry(entry: dict) -> dict[str, Any]:
    """JSON body for second ``POST /products`` after Render merge (full ``integration_config``)."""
    pid = str(entry.get("product_id", "")).strip()
    if not pid:
        raise ConnectorRegistrationHttpError("merged entry missing product_id")
    raw_ce = entry.get("contact_email", "")
    ce = str(raw_ce).strip() if raw_ce is not None else ""
    if not ce:
        raise ConnectorRegistrationHttpError(
            "merged entry missing contact_email (required for POST /products)"
        )
    return {
        "product_id": pid,
        "contact_email": ce,
        "webhook_secret": entry.get("webhook_secret", entry.get("secret", "")),
        "integration_type": entry.get("integration_type", "webhook"),
        "integration_config": dict(entry.get("integration_config") or {}),
        "forward_url": entry.get("forward_url", ""),
        "forward_secret": entry.get("forward_secret", ""),
    }


async def post_register_product_payload(
    *,
    connector_url: str,
    admin_key: str,
    payload: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """POST ``payload`` to ``/products``; return JSON body on HTTP 201."""
    timeout = onboard_connector_http_timeout_seconds()
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    tty = _registration_tty_ui()

    key = (admin_key or "").strip()
    headers: dict[str, str] = {}
    if key:
        headers["X-Admin-Key"] = key

    async def _do_post() -> httpx.Response:
        return await c.post(
            f"{connector_url.rstrip('/')}/products",
            json=payload,
            headers=headers,
        )

    try:
        try:
            if tty:
                from rich.console import Console

                console = Console(stderr=True)
                with console.status("Registering product...", spinner="dots"):
                    resp = await _do_post()
            else:
                resp = await _do_post()
        except httpx.RequestError as post_exc:
            if tty:
                reason = str(post_exc).strip() or type(post_exc).__name__
                if len(reason) > 800:
                    reason = reason[:800] + "…"
                print(
                    f"✗ Registration failed — {reason}. Please re-register.",
                    flush=True,
                )
            raise ConnectorRegistrationHttpError(
                _connector_transport_user_message(connector_url, post_exc),
            ) from post_exc
        except Exception as post_exc:
            if tty:
                reason = str(post_exc).strip() or type(post_exc).__name__
                if len(reason) > 800:
                    reason = reason[:800] + "…"
                print(
                    f"✗ Registration failed — {reason}. Please re-register.",
                    flush=True,
                )
            raise

        if resp.status_code == 201:
            if tty:
                print("✓ Product registered successfully", flush=True)
            return resp.json()
        safe_text = redact_connector_error_response_text(resp.text)
        if tty:
            reason = (safe_text or "").strip() or f"HTTP {resp.status_code}"
            if len(reason) > 800:
                reason = reason[:800] + "…"
            print(
                f"✗ Registration failed — {reason}. Please re-register.",
                flush=True,
            )
        if resp.status_code == 409:
            raise ProductAlreadyRegisteredError(
                f"connector returned HTTP 409: {safe_text}",
                status_code=409,
                response_text=safe_text,
            )
        raise ConnectorRegistrationHttpError(
            f"connector returned HTTP {resp.status_code}: {safe_text}",
            status_code=resp.status_code,
            response_text=safe_text,
        )
    finally:
        if own_client:
            await c.aclose()


async def post_register_product_cli(
    *,
    connector_url: str,
    admin_key: str,
    product_id: str,
    contact_email: str,
    webhook_secret: str,
    integration_type: str,
    forward_url: str,
    forward_secret: str,
    force_reregister: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """First onboard registration (CLI-style ``integration_config``)."""
    payload = build_register_payload_from_cli(
        product_id=product_id,
        contact_email=contact_email,
        webhook_secret=webhook_secret,
        integration_type=integration_type,
        forward_url=forward_url,
        forward_secret=forward_secret,
    )
    payload["force_reregister"] = force_reregister
    return await post_register_product_payload(
        connector_url=connector_url,
        admin_key=admin_key,
        payload=payload,
        client=client,
    )


async def post_register_product_merged_row(
    *,
    connector_url: str,
    admin_key: str,
    entry: dict,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Re-post merged ``PRODUCTS_CONFIG`` row to align Redis with Render."""
    payload = build_register_payload_from_merged_entry(entry)
    payload["force_reregister"] = True
    return await post_register_product_payload(
        connector_url=connector_url,
        admin_key=admin_key,
        payload=payload,
        client=client,
    )
