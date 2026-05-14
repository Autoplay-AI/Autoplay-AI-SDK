"""Shared product onboarding orchestration (canonical implementation).

Single async runner for programmatic onboarding (:func:`run_product_onboarding`)
and higher-level helpers such as :func:`onboard_product`. Library code raises
exceptions; callers map them to stderr + exit as needed.

External CLI scripts may duplicate this flow for convenience;
future work is to rely on the SDK only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from autoplay_sdk.admin.connector_registration_http import (
    ConnectorRegistrationHttpError,
    post_register_product_cli,
)
from autoplay_sdk.admin.onboarding_constants import (
    PRODUCTS_CONFIG_MERGE_LOCAL_ENV_VAR,
    onboard_connector_http_timeout_seconds,
)
from autoplay_sdk.admin.render_products_config import default_merge_local_path


class UnkeyOnboardingError(Exception):
    """Unkey key creation failed or env is misconfigured."""


class MergedPostRegistrationHttpError(ConnectorRegistrationHttpError):
    """Reserved for backwards compatibility; dual-write onboarding uses a single POST."""


@dataclass
class OnboardingRunParams:
    """Parameters for :func:`run_product_onboarding`."""

    connector_url: str
    admin_key: str
    product_id: str
    contact_email: str
    webhook_secret: str
    integration_type: str = "event_stream"
    forward_url: str = ""
    forward_secret: str = ""
    render_api_key: str | None = None
    render_service_id: str | None = None
    merge_local_path: Path | None = None
    no_unkey: bool = False
    key_name: str | None = None
    print_operator_summary: bool = True
    """Print PostHog / Unkey copy-paste block after success."""
    quiet: bool = False
    """If True, skip step progress prints (still prints summary if enabled)."""
    connector_http_timeout_seconds: float | None = None
    """Override default ``POST /products`` httpx timeout when creating the client."""
    force_reregister: bool = False
    """Set true to overwrite an existing ``product_id`` (new webhook_secret, etc.)."""


@dataclass
class OnboardingRunResult:
    product_id: str
    webhook_url: str
    stream_url: str
    webhook_secret: str
    integration_type: str
    render_sync_performed: bool
    connector_response: dict[str, Any]
    unkey_key: str | None = None
    unkey_key_id: str | None = None


def resolve_merge_local_path(merge_local_path: Path | None) -> Path:
    """Resolve merge-local path (used by scripts); ignored by single-POST onboarding."""
    if merge_local_path is not None:
        return merge_local_path
    raw = os.getenv(PRODUCTS_CONFIG_MERGE_LOCAL_ENV_VAR, "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_merge_local_path()


def print_onboarding_operator_summary(
    result: OnboardingRunResult,
    *,
    connector_url: str,
) -> None:
    """Print the operator-facing PostHog / Unkey summary block."""
    _print_summary(
        connector_url=connector_url,
        product_id=result.product_id,
        webhook_secret=result.webhook_secret,
        integration_type=result.integration_type,
        unkey_key=result.unkey_key,
        key_id=result.unkey_key_id,
    )


def _print_summary(
    *,
    connector_url: str,
    product_id: str,
    webhook_secret: str,
    integration_type: str,
    unkey_key: str | None,
    key_id: str | None,
) -> None:
    webhook_url = f"{connector_url.rstrip('/')}/webhook/{product_id}"
    stream_url = f"{connector_url.rstrip('/')}/stream/{product_id}"

    print()
    print("=" * 60)
    print(f"  Product registered: {product_id}")
    print("=" * 60)
    print()
    print("  PostHog destination config")
    print("  --------------------------")
    print(f"  Webhook URL      :  {webhook_url}")
    print(f"  X-PostHog-Secret :  {webhook_secret}")
    print()

    if unkey_key:
        print("  Unkey API key (share with customer — shown once)")
        print("  ------------------------------------------------")
        print(f"  key    :  {unkey_key}")
        print(f"  key_id :  {key_id}")
        print()
        print("  The customer authenticates SSE connections with:")
        print(f"    Authorization: Bearer {unkey_key}")
        print(f"    GET {stream_url}")
        print()

    print("  Next steps")
    print("  ----------")
    print("  1. In PostHog → Data pipelines → Destinations, add a webhook:")
    print(f"       URL    : {webhook_url}")
    print(f"       Header : X-PostHog-Secret: {webhook_secret}")
    if integration_type == "event_stream" and unkey_key:
        print("  2. Share the Unkey key above with the customer.")
        print("     They pass it as 'Authorization: Bearer <key>' on the SSE endpoint.")
    print()


def _urls(connector_url: str, product_id: str) -> tuple[str, str]:
    base = connector_url.rstrip("/")
    return f"{base}/webhook/{product_id}", f"{base}/stream/{product_id}"


async def run_product_onboarding(
    params: OnboardingRunParams,
    *,
    client: httpx.AsyncClient | None = None,
) -> OnboardingRunResult:
    """Run onboarding: ``POST /products`` on the connector; Unkey keys are created server-side.

    The connector holds Render and Unkey credentials; higher-level
    :func:`~autoplay_sdk.admin.onboard.onboard_product` passes ``product_id`` and
    ``contact_email`` (``POST /products`` is open registration). Response JSON includes ``unkey_key`` /
    ``unkey_key_id`` for ``event_stream`` registrations.
    """
    own_client = client is None
    _timeout = (
        params.connector_http_timeout_seconds
        if params.connector_http_timeout_seconds is not None
        else onboard_connector_http_timeout_seconds()
    )
    http_client = client or httpx.AsyncClient(timeout=_timeout)
    try:
        return await _run_product_onboarding_impl(params, http_client)
    finally:
        if own_client:
            await http_client.aclose()


async def _run_product_onboarding_impl(
    params: OnboardingRunParams,
    http_client: httpx.AsyncClient,
) -> OnboardingRunResult:
    connector_url = params.connector_url
    admin_key = params.admin_key
    product_id = params.product_id.strip()
    webhook_secret = params.webhook_secret
    integration_type = params.integration_type
    forward_url = params.forward_url
    forward_secret = params.forward_secret

    def _say(msg: str) -> None:
        if not params.quiet:
            print(msg)

    _say("\nOnboarding customer: {}".format(product_id))
    _say(f"  contact_email    : {params.contact_email.strip()}")
    _say(f"  integration_type : {integration_type}")
    _say(f"  connector_url    : {connector_url}")
    _say("")

    _say("Registering product on connector (Redis + Render dual-write on server)...")
    try:
        first_body = await post_register_product_cli(
            connector_url=connector_url,
            admin_key=admin_key,
            product_id=product_id,
            contact_email=params.contact_email,
            webhook_secret=webhook_secret,
            integration_type=integration_type,
            forward_url=forward_url,
            forward_secret=forward_secret,
            force_reregister=params.force_reregister,
            client=http_client,
        )
    except ConnectorRegistrationHttpError as exc:
        raise ConnectorRegistrationHttpError(
            str(exc),
            status_code=exc.status_code,
            response_text=exc.response_text,
        ) from exc
    _say("  done.")

    render_sync_performed = bool(first_body.get("dual_write"))

    unkey_key = (first_body.get("unkey_key") or "").strip() or None
    unkey_key_id = (first_body.get("unkey_key_id") or "").strip() or None
    effective_webhook_secret = (
        first_body.get("webhook_secret") or ""
    ).strip() or webhook_secret

    if not params.no_unkey and integration_type == "event_stream":
        if not unkey_key or not unkey_key_id:
            raise UnkeyOnboardingError(
                "Connector response missing unkey_key / unkey_key_id. "
                "Upgrade the event connector to a version that creates Unkey keys on POST /products."
            )

    webhook_url, stream_url = _urls(connector_url, product_id)
    result = OnboardingRunResult(
        product_id=product_id,
        webhook_url=webhook_url,
        stream_url=stream_url,
        webhook_secret=effective_webhook_secret,
        integration_type=integration_type,
        render_sync_performed=render_sync_performed,
        connector_response=first_body,
        unkey_key=unkey_key,
        unkey_key_id=unkey_key_id,
    )

    if params.print_operator_summary:
        print_onboarding_operator_summary(result, connector_url=connector_url)

    return result
