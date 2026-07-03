"""Trusted-operator onboarding against the AWS activity connector.

:func:`onboard_product` requires ``product_id``, ``contact_email``, and a
``user_activity_provider``. It calls the connector ``POST /products`` (**open
registration**, no admin header); the connector provisions an inbound
``ingest_secret`` and a scoped MCP read key (``mcp_key``) and returns them —
**once** — in the JSON body. Those secrets live only on the connector.

New customers onboard onto the AWS connector (default
``https://connector.autoplay.ai``). The legacy Render onboarding flow lives in
:mod:`autoplay_sdk.admin.product_onboarding` / :mod:`autoplay_sdk.admin.onboard`
and is unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from autoplay_sdk.admin.connector_registration_http import (
    ConnectorRegistrationHttpError,
    ProductAlreadyRegisteredError,
    post_aws_register_product,
)
from autoplay_sdk.admin.product_onboarding import (
    MergedPostRegistrationHttpError,
    UnkeyOnboardingError,
)
from autoplay_sdk.providers.base import ActivityProvider
from autoplay_sdk.providers import AmplitudeProvider, PostHogProvider

DEFAULT_CONNECTOR_URL = "https://connector.autoplay.ai"

_PROVIDER_REGISTRY: dict[str, ActivityProvider] = {
    "posthog": PostHogProvider(),
    "amplitude": AmplitudeProvider(),
}

_INVALID_PROVIDER_MESSAGE = (
    "Invalid provider {given!r}. "
    "Expected one of: {valid}. "
    "Check for typos — provider names are case-sensitive and lowercase. "
    "Alternatively, pass a provider instance directly: "
    "user_activity_provider=AmplitudeProvider()."
)


def _resolve_provider(
    provider: str | ActivityProvider | None,
) -> ActivityProvider:
    """Accept a provider slug string or an ``ActivityProvider`` instance.

    Raises :class:`ValueError` when ``provider`` is missing or a string that
    does not match any registered provider name.
    """
    if isinstance(provider, ActivityProvider):
        return provider
    if provider is None:
        raise ValueError(
            "user_activity_provider is required — pass a provider instance "
            '(e.g. AmplitudeProvider()) or a slug (e.g. "amplitude").'
        )
    slug = str(provider).strip().lower()
    if slug in _PROVIDER_REGISTRY:
        return _PROVIDER_REGISTRY[slug]
    valid = ", ".join(f'"{k}"' for k in sorted(_PROVIDER_REGISTRY))
    raise ValueError(_INVALID_PROVIDER_MESSAGE.format(given=provider, valid=valid))


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
    "Use a stable slug for your product (e.g. the value you pass to your activity "
    "provider's identify call) so ingest events map to your tenant."
)

_EMPTY_CONTACT_EMAIL_USER_MESSAGE = (
    "Please provide a non-empty contact_email to onboard_product "
    "(valid email required by POST /products)."
)


@dataclass
class OnboardProductResult:
    """Successful ``onboard_product`` registration on the AWS connector.

    ``ingest_url``, ``ingest_secret``, and ``mcp_key`` are guaranteed non-empty
    on a successful call; if the connector omits any of them a
    :class:`RuntimeError` is raised instead of returning an incomplete result.

    - ``ingest_url``   — the customer configures their activity provider to POST
                         session events here.
    - ``ingest_secret``— the inbound auth secret (shown once).
    - ``ingest_auth``  — human hint for how to attach ``ingest_secret``
                         (e.g. ``"Authorization: Bearer <ingest_secret>"``).
    - ``mcp_url`` / ``mcp_key`` / ``mcp_auth`` — the agent connects to the MCP
                         endpoint with ``mcp_key`` to pull live user activity.
    """

    product_id: str
    provider: str
    ingest_url: str
    ingest_secret: str
    ingest_auth: str
    mcp_url: str
    mcp_key: str
    mcp_auth: str
    connector_response: dict[str, Any]


def _aws_result_from_response(response: dict[str, Any]) -> OnboardProductResult:
    """Build the SDK result from the connector ``POST /products`` body.

    Requires ``ingest_url``, ``ingest_secret``, and ``mcp_key`` — the minimum a
    customer needs to send events and have their agent read them back.
    """
    creds = response.get("credentials")
    setup = response.get("setup")
    creds = creds if isinstance(creds, dict) else {}
    setup = setup if isinstance(setup, dict) else {}

    ingest_url = str(setup.get("ingest_url") or "").strip()
    ingest_secret = str(creds.get("ingest_secret") or "").strip()
    mcp_key = str(creds.get("mcp_key") or "").strip()

    missing: list[str] = []
    if not ingest_url:
        missing.append("setup.ingest_url")
    if not ingest_secret:
        missing.append("credentials.ingest_secret")
    if not mcp_key:
        missing.append("credentials.mcp_key")
    if missing:
        raise RuntimeError(
            "Product registration did not return all required fields: "
            + "; ".join(missing)
            + ". Check the connector version and configuration."
        )

    return OnboardProductResult(
        product_id=str(response.get("product_id") or "").strip(),
        provider=str(response.get("provider") or "").strip(),
        ingest_url=ingest_url,
        ingest_secret=ingest_secret,
        ingest_auth=str(setup.get("ingest_auth") or "").strip(),
        mcp_url=str(setup.get("mcp_url") or "").strip(),
        mcp_key=mcp_key,
        mcp_auth=str(setup.get("mcp_auth") or "").strip(),
        connector_response=response,
    )


def print_onboarding_operator_summary(result: OnboardProductResult) -> None:
    """Print the copy-paste ingest + MCP setup block for a registered product."""
    print()
    print("=" * 60)
    print(f"  Product registered: {result.product_id}  (provider: {result.provider})")
    print("=" * 60)
    print()
    print("  Inbound events — configure your activity provider")
    print("  -------------------------------------------------")
    print(f"  Ingest URL     :  {result.ingest_url}")
    print(
        f"  Auth           :  {result.ingest_auth or 'Authorization: Bearer <ingest_secret>'}"
    )
    print(f"  ingest_secret  :  {result.ingest_secret}")
    print()
    print("  Agent reads activity — MCP endpoint")
    print("  -----------------------------------")
    print(f"  MCP URL        :  {result.mcp_url}")
    print(f"  Auth           :  {result.mcp_auth or 'Authorization: Bearer <mcp_key>'}")
    print(f"  mcp_key        :  {result.mcp_key}")
    print()
    print("  Secrets above are shown once and cannot be retrieved later.")
    print()


async def onboard_product(
    product_id: str,
    *,
    contact_email: str,
    connector_url: str | None = None,
    ingest_secret: str | None = None,
    force: bool = False,
    print_operator_summary: bool = False,
    connector_http_timeout_seconds: float | None = None,
    user_activity_provider: str | ActivityProvider,
    client: httpx.AsyncClient | None = None,
) -> OnboardProductResult:
    """Register a product on the **AWS activity connector**.

    Sends ``product_id``, ``contact_email``, and ``provider`` (derived from
    ``user_activity_provider``) to ``POST /products`` — open registration, no
    admin header. The connector provisions the inbound ``ingest_secret`` and the
    scoped ``mcp_key`` and returns them once.

    Args:
        product_id:    Stable slug for the product (e.g. ``"acme"``).
        contact_email: Owner e-mail for this product registration.
        connector_url: Override the default connector base URL.
        ingest_secret: Optional preset inbound secret; the connector mints one
                       when omitted.
        force:         Overwrite an existing ``product_id`` registration.
        user_activity_provider: Provider instance or slug (``PostHogProvider()``
                       / ``AmplitudeProvider()`` / ``"amplitude"``).

    Raises :class:`ConnectorRegistrationHttpError` on transport or HTTP errors,
    and :class:`ProductAlreadyRegisteredError` on HTTP 409 when ``force`` is false.
    """
    provider = _resolve_provider(user_activity_provider)

    pid = product_id.strip()
    if not pid:
        raise ValueError(_EMPTY_PRODUCT_ID_USER_MESSAGE)
    cem = (contact_email or "").strip()
    if not cem:
        raise ValueError(_EMPTY_CONTACT_EMAIL_USER_MESSAGE)
    base = ((connector_url or "").strip() or DEFAULT_CONNECTOR_URL).rstrip("/")

    own_client = client is None and connector_http_timeout_seconds is not None
    http_client = client
    if own_client:
        http_client = httpx.AsyncClient(timeout=connector_http_timeout_seconds)
    try:
        response = await post_aws_register_product(
            connector_url=base,
            product_id=pid,
            contact_email=cem,
            provider=provider.name,
            ingest_secret=(ingest_secret or "").strip(),
            force=force,
            client=http_client,
        )
    finally:
        if own_client and http_client is not None:
            await http_client.aclose()

    result = _aws_result_from_response(response)
    if print_operator_summary:
        print_onboarding_operator_summary(result)
    return result


def onboard_product_sync(
    product_id: str,
    *,
    contact_email: str,
    connector_url: str | None = None,
    ingest_secret: str | None = None,
    force: bool = False,
    print_operator_summary: bool = False,
    connector_http_timeout_seconds: float | None = None,
    user_activity_provider: str | ActivityProvider,
    client: httpx.AsyncClient | None = None,
) -> OnboardProductResult:
    """Synchronous wrapper for :func:`onboard_product`."""
    return asyncio.run(
        onboard_product(
            product_id,
            contact_email=contact_email,
            connector_url=connector_url,
            ingest_secret=ingest_secret,
            force=force,
            print_operator_summary=print_operator_summary,
            connector_http_timeout_seconds=connector_http_timeout_seconds,
            user_activity_provider=user_activity_provider,
            client=client,
        )
    )
