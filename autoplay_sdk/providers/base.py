"""autoplay_sdk.providers.base — Abstract interface for activity / session-replay providers.

Defines the unified data contract (``ProviderRegistrationBody``) and the
``ActivityProvider`` abstract base class that every provider (PostHog,
Amplitude, FullStory, …) must implement.  Core SDK code depends only on
these abstractions; provider-specific logic lives in its own sub-package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderRegistrationBody:
    """Standardized webhook registration config for any activity provider.

    Each ``ActivityProvider`` produces one of these from its own configuration
    so that the admin helpers can register products with the Autoplay connector
    without knowing which specific provider is in use.

    Attributes:
        provider_name:        Short slug identifying the provider (e.g. ``"posthog"``).
        webhook_url:          URL the provider will POST session events to (Autoplay
                              connector ``/webhook/{product_id}`` endpoint).
        webhook_secret:       Secret the Autoplay connector uses to authenticate
                              inbound requests from this provider.
        auth_header_name:     HTTP header name the provider attaches (e.g.
                              ``"X-PostHog-Secret"`` or ``"X-Amplitude-Signature"``).
        sensitive_config_keys: Additional JSON key names (lowercase) that must be
                              redacted from connector error responses — provider-specific
                              aliases for ``webhook_secret`` (e.g. ``"x_posthog_secret"``).
    """

    provider_name: str
    webhook_url: str
    webhook_secret: str
    auth_header_name: str
    sensitive_config_keys: frozenset[str] = field(default_factory=frozenset)


class ActivityProvider(ABC):
    """Abstract base for session-replay / analytics event providers.

    Implement this class to add support for a new provider.  The SDK core
    depends only on this interface; PostHog-specific logic is isolated in
    ``autoplay_sdk.providers.posthog``.

    Example (implementing a hypothetical Amplitude provider)::

        class AmplitudeProvider(ActivityProvider):
            @property
            def name(self) -> str:
                return "amplitude"

            def build_registration_body(self, webhook_url, webhook_secret):
                return ProviderRegistrationBody(
                    provider_name=self.name,
                    webhook_url=webhook_url,
                    webhook_secret=webhook_secret,
                    auth_header_name="X-Amplitude-Secret",
                    sensitive_config_keys=frozenset({"x_amplitude_secret"}),
                )

            def get_session_id_js(self) -> str:
                return "amplitude.getSessionId()?.toString() ?? null"

            def format_operator_summary(self, *, connector_url, product_id,
                                         webhook_secret, integration_type,
                                         unkey_key, key_id):
                ...
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short lowercase slug identifying this provider (e.g. ``"posthog"``)."""
        ...

    @abstractmethod
    def build_registration_body(
        self,
        webhook_url: str,
        webhook_secret: str,
    ) -> ProviderRegistrationBody:
        """Return a ``ProviderRegistrationBody`` for this provider's webhook config.

        Args:
            webhook_url:    Autoplay connector webhook URL for the product.
            webhook_secret: Secret used to authenticate inbound provider requests.

        Returns:
            Fully populated ``ProviderRegistrationBody`` with provider-specific
            ``auth_header_name`` and ``sensitive_config_keys``.
        """
        ...

    @abstractmethod
    def get_session_id_js(self) -> str:
        """Return a JS expression that resolves to the active session ID in the browser.

        The expression is injected into browser-side snippets (e.g. the Intercom
        session-link script) so the correct provider SDK is called at runtime.

        Returns:
            A self-contained JS expression string — no trailing semicolon.
            Must evaluate to the session ID string or ``null`` when unavailable.

        Example (PostHog)::

            "typeof posthog !== 'undefined' ? posthog.get_session_id() : null"
        """
        ...

    @abstractmethod
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
        """Print the operator-facing onboarding copy-paste block for this provider.

        Args:
            connector_url:    Base URL of the Autoplay event connector.
            product_id:       Registered product identifier.
            webhook_secret:   Secret to configure in the provider's webhook destination.
            integration_type: ``"event_stream"`` or ``"webhook"``.
            unkey_key:        Unkey bearer token (``None`` when not created).
            key_id:           Unkey key ID (``None`` when not created).
        """
        ...


__all__ = ["ActivityProvider", "ProviderRegistrationBody"]
