"""autoplay_sdk.providers — Activity / session-replay provider abstractions.

Exports the ``ActivityProvider`` abstract base class and ``ProviderRegistrationBody``
unified data contract, plus the built-in ``PostHogProvider`` implementation.

To add a new provider (e.g. Amplitude), subclass ``ActivityProvider`` and
implement its four abstract methods.  The SDK core depends only on
``ActivityProvider``; no core file needs to import from a provider sub-package.
"""

from .base import ActivityProvider, ProviderRegistrationBody
from .posthog import PostHogProvider

__all__ = ["ActivityProvider", "PostHogProvider", "ProviderRegistrationBody"]
