"""autoplay_sdk.providers.amplitude.provider — Amplitude ActivityProvider implementation.

Isolates all Amplitude-specific constants, browser-side session-ID resolution,
and the operator onboarding summary into one place.  The rest of the SDK
references only ``ActivityProvider`` from ``autoplay_sdk.providers.base``.

Key differences from PostHog
-----------------------------
* Amplitude events are delivered to ``/ingest/amplitude/{product_id}`` (NOT
  the PostHog ``/webhook/{product_id}`` endpoint — those accept different
  payload formats and use different auth schemes).
* Authentication uses ``Authorization: Bearer {unkey_key}`` — Amplitude's
  HTTP destination supports Bearer token auth, which is the same Unkey key
  used for SSE.  No separate webhook-secret header is required.
* ``amplitude.getSessionId()`` returns a *numeric* Unix-millisecond timestamp
  (``number | undefined``).  The JS expression stringifies it with ``String()``
  so the session store always receives a string value.
"""

from __future__ import annotations

from autoplay_sdk.providers.base import ActivityProvider, ProviderRegistrationBody


class AmplitudeProvider(ActivityProvider):
    """ActivityProvider for Amplitude session replay / analytics.

    Setup path for operators::

        from autoplay_sdk.providers import AmplitudeProvider

        result = await onboard_product(
            "my_product",
            contact_email="owner@example.com",
            user_activity_provider=AmplitudeProvider(),
            print_operator_summary=True,
        )

        # In Amplitude Data → Connections → Event Streaming → HTTP:
        #   Endpoint URL   : {connector}/ingest/amplitude/{product_id}
        #   Authentication : Bearer Token
        #   Token          : result.unkey_key

    Browser JS expression for session linking::

        js = AmplitudeProvider().get_session_id_js()
        # "typeof amplitude !== 'undefined' && amplitude.getSessionId() != null
        #     ? String(amplitude.getSessionId()) : null"
    """

    # Amplitude HTTP destination uses Bearer token auth ("Authorization: Bearer …").
    AUTH_HEADER_NAME: str = "Authorization"

    # Config key alias for the Bearer token if stored in PRODUCTS_CONFIG YAML;
    # must be redacted from connector error logs.
    SENSITIVE_CONFIG_KEY: str = "amplitude_bearer_token"

    @property
    def name(self) -> str:
        return "amplitude"

    def build_registration_body(
        self,
        webhook_url: str,
        webhook_secret: str,
    ) -> ProviderRegistrationBody:
        # For Amplitude the "webhook_url" is the /ingest/amplitude/{product_id}
        # endpoint and the "webhook_secret" is the Unkey Bearer token.
        return ProviderRegistrationBody(
            provider_name=self.name,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            auth_header_name=self.AUTH_HEADER_NAME,
            sensitive_config_keys=frozenset({self.SENSITIVE_CONFIG_KEY}),
        )

    def get_session_id_js(self) -> str:
        # amplitude.getSessionId() returns number | undefined (Browser SDK 2.x).
        # String() converts the numeric timestamp to a string; null when absent.
        return (
            "typeof amplitude !== 'undefined' && amplitude.getSessionId() != null"
            " ? String(amplitude.getSessionId()) : null"
        )

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
        """Print the Amplitude / Unkey copy-paste onboarding block.

        Amplitude events go to ``/ingest/amplitude/{product_id}`` (NOT the
        PostHog ``/webhook/{product_id}`` endpoint).  Auth is Bearer token —
        use ``result.unkey_key`` from ``onboard_product``.
        """
        # Amplitude uses a dedicated ingest path, not the PostHog /webhook/ path.
        ingest_url = f"{connector_url.rstrip('/')}/ingest/amplitude/{product_id}"
        stream_url = f"{connector_url.rstrip('/')}/stream/{product_id}"

        print()
        print("=" * 60)
        print(f"  Product registered: {product_id}")
        print("=" * 60)
        print()
        print("  Amplitude HTTP destination config")
        print("  ----------------------------------")
        print(f"  Ingest URL     :  {ingest_url}")
        if unkey_key:
            print(f"  Bearer Token   :  {unkey_key}")
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
        print("  1. In Amplitude → Data → Connections → Event Streaming,")
        print("     create a new destination → HTTP:")
        print(f"       Endpoint URL   : {ingest_url}")
        print("       Authentication : Bearer Token")
        if unkey_key:
            print(f"       Token          : {unkey_key}")
        print("       Events to send : All events")
        if integration_type == "event_stream" and unkey_key:
            print("  2. Share the Unkey key above with the customer.")
            print(
                "     They use the same key as 'Authorization: Bearer <key>'"
                " on the SSE endpoint."
            )
        print()


__all__ = ["AmplitudeProvider"]
