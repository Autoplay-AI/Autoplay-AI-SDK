"""autoplay_sdk.providers — Activity / session-replay provider abstractions.

Exports the ``ActivityProvider`` abstract base class and ``ProviderRegistrationBody``
unified data contract, plus the built-in provider implementations.

To add a new provider, subclass ``ActivityProvider`` and implement its four
abstract methods.  The SDK core depends only on ``ActivityProvider``; no core
file needs to import from a provider sub-package.
"""

from .base import ActivityProvider, ProviderRegistrationBody
from .posthog import PostHogProvider
from .amplitude import AmplitudeProvider

__all__ = [
    "ActivityProvider",
    "AmplitudeProvider",
    "PostHogProvider",
    "ProviderRegistrationBody",
]
