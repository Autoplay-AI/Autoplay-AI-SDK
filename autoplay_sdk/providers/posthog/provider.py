"""autoplay_sdk.providers.posthog.provider — PostHog ActivityProvider implementation.

Isolates all PostHog-specific constants, browser-side session-ID resolution,
and the operator onboarding summary into one place.  The rest of the SDK
references only ``ActivityProvider`` from ``autoplay_sdk.providers.base``.
"""

from __future__ import annotations

import httpx

from autoplay_sdk.providers.base import ActivityProvider, ProviderRegistrationBody
from autoplay_sdk.providers.posthog.destination import (
    DestinationResult,
    DestinationStatus,
    check_destination_status,
    create_or_update_destination,
)


class PostHogProvider(ActivityProvider):
    """ActivityProvider for PostHog session replay / analytics.

    Covers the original ("OG") PostHog integration formula:

    * Webhook destination configured with ``X-PostHog-Secret`` header.
    * Browser snippet calls ``posthog.get_session_id()`` to link sessions.
    * Operator summary prints the PostHog → Data pipelines → Destinations
      copy-paste block unchanged from the pre-refactor implementation.

    Usage::

        from autoplay_sdk.providers import PostHogProvider

        provider = PostHogProvider()

        # Registration body for connector POST /products
        body = provider.build_registration_body(
            webhook_url="https://connector.example.com/webhook/my_product",
            webhook_secret="whsec_...",
        )
        # body.auth_header_name == "X-PostHog-Secret"

        # Browser JS expression for session linking
        js = provider.get_session_id_js()
        # "typeof posthog !== 'undefined' ? posthog.get_session_id() : null"
    """

    # PostHog webhook destination header.
    AUTH_HEADER_NAME: str = "X-PostHog-Secret"

    # Legacy config key name used as an alias for webhook_secret in some
    # PRODUCTS_CONFIG YAML rows; must be redacted from connector error logs.
    SENSITIVE_CONFIG_KEY: str = "x_posthog_secret"

    @property
    def name(self) -> str:
        return "posthog"

    def build_registration_body(
        self,
        webhook_url: str,
        webhook_secret: str,
    ) -> ProviderRegistrationBody:
        return ProviderRegistrationBody(
            provider_name=self.name,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            auth_header_name=self.AUTH_HEADER_NAME,
            sensitive_config_keys=frozenset({self.SENSITIVE_CONFIG_KEY}),
        )

    def get_session_id_js(self) -> str:
        return "typeof posthog !== 'undefined' ? posthog.get_session_id() : null"

    def format_operator_summary(
        self,
        *,
        connector_url: str,
        product_id: str,
        webhook_secret: str,
        integration_type: str,
        unkey_key: str | None,
        key_id: str | None,
    ) -> None:
        """Print the PostHog / Unkey copy-paste onboarding block.

        Preserves the exact output of the original ``_print_summary()`` in
        ``autoplay_sdk.admin.product_onboarding`` so existing operator
        workflows are unaffected.
        """
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
            print(
                "     They pass it as 'Authorization: Bearer <key>' on the SSE endpoint."
            )
        print()

    async def create_destination(
        self,
        *,
        host: str,
        project_id: str,
        personal_api_key: str,
        webhook_url: str,
        webhook_secret: str,
        client: httpx.AsyncClient | None = None,
    ) -> DestinationResult:
        """Create/update the Autoplay destination in PostHog (idempotent).

        Deterministic replacement for the old agent-driven "create the
        hog_function" step: it consumes the ``webhook_url`` / ``webhook_secret``
        returned by ``onboard_product`` and makes the PostHog API call directly.

        Intentionally provider-specific (not on ``ActivityProvider``): PostHog
        needs host/project/personal-key, other providers differ. We lift it to
        the base interface only once a second provider pins the shared shape.
        """
        return await create_or_update_destination(
            host=host,
            project_id=project_id,
            personal_api_key=personal_api_key,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            client=client,
        )

    async def verify(
        self,
        *,
        host: str,
        project_id: str,
        personal_api_key: str,
        destination_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> DestinationStatus:
        """Provider-specific verification: destination present and enabled?

        Confirms PostHog still has the destination and that it's enabled (so it
        will forward events). This is the PostHog-side config check; the
        end-to-end "an event actually arrived" proof is observed connector-side.
        """
        return await check_destination_status(
            host=host,
            project_id=project_id,
            personal_api_key=personal_api_key,
            destination_id=destination_id,
            client=client,
        )


__all__ = ["PostHogProvider"]
