"""Trusted-operator onboarding (``event_stream`` only in v1).

:func:`onboard_product` requires ``product_id``, ``contact_email``, and optional
URL / behavior flags. It calls the connector ``POST /products`` (**open
registration**, no admin header); the connector creates Unkey + webhook
credentials and returns them in the JSON body. Unkey / Render secrets live
**only** on the connector.

Repo-local ``scripts/onboard_customer.py`` uses :func:`run_product_onboarding`
with explicit params for shell/CI flows.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from autoplay_sdk.admin.connector_registration_http import (
    ConnectorRegistrationHttpError,
    ProductAlreadyRegisteredError,
)
from autoplay_sdk.admin.product_onboarding import (
    MergedPostRegistrationHttpError,
    OnboardingRunParams,
    OnboardingRunResult,
    UnkeyOnboardingError,
    print_onboarding_operator_summary as _print_onboarding_operator_summary,
    run_product_onboarding,
)

DEFAULT_CONNECTOR_URL = "https://your-connector.example.com"

__all__ = [
    "DEFAULT_CONNECTOR_URL",
    "ConnectorRegistrationHttpError",
    "MergedPostRegistrationHttpError",
    "ProductAlreadyRegisteredError",
    "OnboardProductResult",
    "UnkeyOnboardingError",
    "onboard_product",
    "onboard_product_sync",
    "print_onboarding_operator_summary",
]

# Shown when callers pass blank product_id (SDK-facing; env validation stays terse).
_EMPTY_PRODUCT_ID_USER_MESSAGE = (
    "Please provide a non-empty product_id to onboard_product. "
    "Use the same stable string you pass as product_id in posthog.identify "
    "(or your chosen product slug) so webhooks and the stream map to your tenant."
)

_EMPTY_CONTACT_EMAIL_USER_MESSAGE = (
    "Please provide a non-empty contact_email to onboard_product "
    "(valid email required by POST /products)."
)


def _connector_base_from_webhook_url(webhook_url: str) -> str:
    """Derive connector origin from absolute webhook URL ``…/webhook/{product_id}``."""
    w = (webhook_url or "").strip()
    marker = "/webhook/"
    idx = w.find(marker)
    if idx == -1:
        return w.rstrip("/")
    return w[:idx].rstrip("/")


def _onboarding_run_params(
    product_id: str,
    *,
    contact_email: str,
    connector_url: str | None,
    webhook_secret: str | None,
    force_reregister: bool,
    print_operator_summary: bool,
    key_name: str | None,
    connector_http_timeout_seconds: float | None,
) -> OnboardingRunParams:
    pid = product_id.strip()
    if not pid:
        raise ValueError(_EMPTY_PRODUCT_ID_USER_MESSAGE)

    cem = (contact_email or "").strip()
    if not cem:
        raise ValueError(_EMPTY_CONTACT_EMAIL_USER_MESSAGE)

    base = ((connector_url or "").strip() or DEFAULT_CONNECTOR_URL).rstrip("/")
    if not base:
        raise ValueError("connector_url resolved empty (unexpected).")

    wsec = (webhook_secret or "").strip() if webhook_secret is not None else ""
    if not wsec:
        wsec = secrets.token_urlsafe(32)

    return OnboardingRunParams(
        connector_url=base,
        admin_key="",
        product_id=pid,
        contact_email=cem,
        webhook_secret=wsec,
        integration_type="event_stream",
        forward_url="",
        forward_secret="",
        render_api_key=None,
        render_service_id=None,
        merge_local_path=None,
        no_unkey=False,
        key_name=key_name or pid,
        print_operator_summary=print_operator_summary,
        quiet=True,
        connector_http_timeout_seconds=connector_http_timeout_seconds,
        force_reregister=force_reregister,
    )


def print_onboarding_operator_summary(
    result: OnboardProductResult,
    *,
    connector_url: str | None = None,
) -> None:
    """Print PostHog / stream setup (same formatted output as after a successful onboarding run).

    Delegates to :func:`autoplay_sdk.admin.product_onboarding.print_onboarding_operator_summary`.
    If ``connector_url`` is omitted, it is inferred from ``result.webhook_url``.
    """
    base = (
        connector_url or _connector_base_from_webhook_url(result.webhook_url)
    ).strip()
    run = OnboardingRunResult(
        product_id=result.product_id,
        webhook_url=result.webhook_url,
        stream_url=result.stream_url,
        webhook_secret=result.webhook_secret,
        integration_type=result.integration_type,
        render_sync_performed=result.render_sync_performed,
        connector_response=result.connector_response,
        unkey_key=result.unkey_key,
        unkey_key_id=result.unkey_key_id,
    )
    _print_onboarding_operator_summary(run, connector_url=base)


@dataclass
class OnboardProductResult:
    """Successful ``onboard_product`` registration.

    On every successful call, ``webhook_url``, ``webhook_secret`` (PostHog
    ``X-PostHog-Secret``), and ``unkey_key`` are non-empty strings, plus
    ``stream_url`` for SSE. If the runner omits any of these, a
    :class:`RuntimeError` is raised instead of returning an incomplete result.
    """

    product_id: str
    webhook_url: str
    stream_url: str
    webhook_secret: str
    integration_type: Literal["event_stream"]
    render_sync_performed: bool
    connector_response: dict[str, Any]
    unkey_key: str
    unkey_key_id: str


def _onboard_product_result_from_run(run: OnboardingRunResult) -> OnboardProductResult:
    """Build the SDK result; require webhook URL, PostHog secret, and Unkey key."""
    wurl = (run.webhook_url or "").strip()
    surl = (run.stream_url or "").strip()
    wsec = (run.webhook_secret or "").strip()
    ukey = (run.unkey_key or "").strip()
    uid = (run.unkey_key_id or "").strip()
    missing: list[str] = []
    if not wurl:
        missing.append("webhook_url (PostHog destination URL)")
    if not surl:
        missing.append("stream_url (SSE endpoint)")
    if not wsec:
        missing.append("webhook_secret (X-PostHog-Secret value)")
    if not ukey:
        missing.append("unkey_key (SSE Bearer token)")
    if not uid:
        missing.append("unkey_key_id")
    if missing:
        raise RuntimeError(
            "Product registration did not return all required credentials: "
            + "; ".join(missing)
            + ". Check connector and Unkey configuration."
        )
    return OnboardProductResult(
        product_id=run.product_id,
        webhook_url=wurl,
        stream_url=surl,
        webhook_secret=wsec,
        integration_type="event_stream",
        render_sync_performed=run.render_sync_performed,
        connector_response=run.connector_response,
        unkey_key=ukey,
        unkey_key_id=uid,
    )


async def onboard_product(
    product_id: str,
    *,
    contact_email: str,
    connector_url: str | None = None,
    webhook_secret: str | None = None,
    force_reregister: bool = False,
    print_operator_summary: bool = False,
    key_name: str | None = None,
    connector_http_timeout_seconds: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> OnboardProductResult:
    """Register an ``event_stream`` product via the **event connector**.

    Sends ``product_id``, ``contact_email``, and optional fields. ``POST /products``
    is open registration (no admin header). The connector creates webhook + Unkey
    credentials and returns them.

    **connector_url** defaults to :data:`DEFAULT_CONNECTOR_URL`; override for
    self-hosted connectors.

    ``webhook_secret``: optional preset PostHog secret; if omitted, a random secret
    is generated before ``POST /products`` (the connector may also generate when
    empty).

    ``force_reregister``: same semantics as ``ONBOARD_FORCE_REREGISTER`` in older
    env-based flows.

    Raises :class:`ConnectorRegistrationHttpError` on transport or HTTP errors.

    Raises :class:`ProductAlreadyRegisteredError` on HTTP 409 when
    ``force_reregister`` is false.
    """
    params = _onboarding_run_params(
        product_id,
        contact_email=contact_email,
        connector_url=connector_url,
        webhook_secret=webhook_secret,
        force_reregister=force_reregister,
        print_operator_summary=print_operator_summary,
        key_name=key_name,
        connector_http_timeout_seconds=connector_http_timeout_seconds,
    )
    run = await run_product_onboarding(params, client=client)
    return _onboard_product_result_from_run(run)


def onboard_product_sync(
    product_id: str,
    *,
    contact_email: str,
    connector_url: str | None = None,
    webhook_secret: str | None = None,
    force_reregister: bool = False,
    print_operator_summary: bool = False,
    key_name: str | None = None,
    connector_http_timeout_seconds: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> OnboardProductResult:
    """Synchronous wrapper for :func:`onboard_product`."""
    return asyncio.run(
        onboard_product(
            product_id,
            contact_email=contact_email,
            connector_url=connector_url,
            webhook_secret=webhook_secret,
            force_reregister=force_reregister,
            print_operator_summary=print_operator_summary,
            key_name=key_name,
            connector_http_timeout_seconds=connector_http_timeout_seconds,
            client=client,
        )
    )
