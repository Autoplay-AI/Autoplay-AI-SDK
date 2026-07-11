"""AWS activity-connector onboarding contract (POST /products).

Covers the AWS-native register payload/response used by the customer-facing
``onboard_product`` after the Layer-1 migration. The legacy Render payload/parse
is exercised separately in ``test_connector_registration_http.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from autoplay_sdk.admin import DEFAULT_CONNECTOR_URL, onboard_product
from autoplay_sdk.admin.connector_registration_http import (
    ProductAlreadyRegisteredError,
    build_aws_register_payload,
    post_aws_register_product,
)
from autoplay_sdk.providers import AmplitudeProvider

_AWS_201_BODY = {
    "product_id": "acme",
    "provider": "amplitude",
    "status": "active",
    "created_at": "2026-07-02T00:00:00Z",
    "credentials": {"ingest_secret": "ing_secret_xyz", "mcp_key": "mcp_key_abc"},
    "setup": {
        "ingest_url": "https://connector.autoplay.ai/ingest/acme",
        "ingest_auth": "Authorization: Bearer <ingest_secret>",
        "mcp_url": "https://mcp.autoplay.ai/mcp",
        "mcp_auth": "Authorization: Bearer <mcp_key>",
    },
    "note": "Secrets are shown once and cannot be retrieved later.",
}


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_build_aws_register_payload_shape() -> None:
    """provider + force always present; ingest_secret only when non-empty."""
    minimal = build_aws_register_payload(
        product_id="acme", contact_email="o@e.com", provider="amplitude"
    )
    assert minimal == {
        "product_id": "acme",
        "contact_email": "o@e.com",
        "provider": "amplitude",
        "force": False,
    }
    with_secret = build_aws_register_payload(
        product_id="acme",
        contact_email="o@e.com",
        provider="posthog",
        ingest_secret="preset",
        force=True,
    )
    assert with_secret["ingest_secret"] == "preset"
    assert with_secret["force"] is True


@pytest.mark.asyncio
async def test_post_aws_register_product_returns_body_on_201() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products"
        return httpx.Response(201, json=_AWS_201_BODY)

    async with _mock_client(handler) as client:
        body = await post_aws_register_product(
            connector_url="https://connector.autoplay.ai",
            product_id="acme",
            contact_email="o@e.com",
            provider="amplitude",
            client=client,
        )
    assert body["credentials"]["mcp_key"] == "mcp_key_abc"


@pytest.mark.asyncio
async def test_post_aws_register_product_409_raises_already_registered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "product already registered"})

    async with _mock_client(handler) as client:
        with pytest.raises(ProductAlreadyRegisteredError):
            await post_aws_register_product(
                connector_url="https://connector.autoplay.ai",
                product_id="acme",
                contact_email="o@e.com",
                provider="amplitude",
                client=client,
            )


@pytest.mark.asyncio
async def test_onboard_product_parses_aws_response_and_sends_provider() -> None:
    """onboard_product posts provider/force to the default URL and maps the
    nested credentials/setup into OnboardProductResult."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json=_AWS_201_BODY)

    async with _mock_client(handler) as client:
        result = await onboard_product(
            "acme",
            contact_email="o@e.com",
            user_activity_provider=AmplitudeProvider(),
            client=client,
        )

    # Default target is the AWS connector.
    assert seen["url"] == f"{DEFAULT_CONNECTOR_URL}/products"
    # Provider is derived from user_activity_provider and force defaults False.
    assert seen["body"]["provider"] == "amplitude"
    assert seen["body"]["force"] is False
    assert "ingest_secret" not in seen["body"]  # omitted → connector mints it

    assert result.provider == "amplitude"
    assert result.ingest_url == "https://connector.autoplay.ai/ingest/acme"
    assert result.ingest_secret == "ing_secret_xyz"
    assert result.mcp_url == "https://mcp.autoplay.ai/mcp"
    assert result.mcp_key == "mcp_key_abc"
    assert result.connector_response == _AWS_201_BODY


@pytest.mark.asyncio
async def test_onboard_product_accepts_provider_slug_and_force() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={**_AWS_201_BODY, "provider": "posthog"})

    async with _mock_client(handler) as client:
        await onboard_product(
            "acme",
            contact_email="o@e.com",
            user_activity_provider="posthog",
            ingest_secret="preset-secret",
            force=True,
            client=client,
        )
    assert seen["body"]["provider"] == "posthog"
    assert seen["body"]["force"] is True
    assert seen["body"]["ingest_secret"] == "preset-secret"


@pytest.mark.asyncio
async def test_onboard_product_missing_credentials_raises_runtime_error() -> None:
    incomplete = {**_AWS_201_BODY, "credentials": {"ingest_secret": "only"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=incomplete)

    async with _mock_client(handler) as client:
        with pytest.raises(RuntimeError) as excinfo:
            await onboard_product(
                "acme",
                contact_email="o@e.com",
                user_activity_provider=AmplitudeProvider(),
                client=client,
            )
    assert "mcp_key" in str(excinfo.value)


@pytest.mark.asyncio
async def test_onboard_product_tolerates_non_dict_credentials_setup() -> None:
    # A malformed 201 with non-dict credentials/setup must raise the clean
    # missing-fields RuntimeError, not AttributeError.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"credentials": "oops", "setup": ["nope"]})

    async with _mock_client(handler) as client:
        with pytest.raises(RuntimeError):
            await onboard_product(
                "acme",
                contact_email="o@e.com",
                user_activity_provider=AmplitudeProvider(),
                client=client,
            )


@pytest.mark.asyncio
async def test_onboard_product_requires_provider() -> None:
    with pytest.raises(ValueError):
        await onboard_product(
            "acme", contact_email="o@e.com", user_activity_provider=None
        )


@pytest.mark.asyncio
async def test_onboard_product_rejects_unknown_provider_slug() -> None:
    with pytest.raises(ValueError):
        await onboard_product(
            "acme", contact_email="o@e.com", user_activity_provider="segment"
        )
