"""Optional admin / operator helpers (do not import from untrusted app code paths)."""

from autoplay_sdk.admin.onboard import (
    DEFAULT_CONNECTOR_URL,
    ConnectorRegistrationHttpError,
    MergedPostRegistrationHttpError,
    OnboardProductResult,
    ProductAlreadyRegisteredError,
    UnkeyOnboardingError,
    onboard_product,
    onboard_product_sync,
    print_onboarding_operator_summary,
)

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
