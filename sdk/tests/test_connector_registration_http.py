"""Transport-layer behavior for connector admin POST /products."""

from __future__ import annotations

import pytest
import httpx

from autoplay_sdk.admin.connector_registration_http import (
    ConnectorRegistrationHttpError,
    post_register_product_payload,
)


@pytest.mark.asyncio
async def test_post_register_product_payload_maps_request_error_to_helpful_message() -> (
    None
):
    """Unreachable connector raises ConnectorRegistrationHttpError, not raw httpx."""

    def _fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated failure", request=request)

    transport = httpx.MockTransport(_fail)
    payload = {
        "product_id": "acme",
        "contact_email": "owner@example.com",
        "webhook_secret": "whsec_test",
        "integration_type": "event_stream",
        "integration_config": {"mode": "sse"},
        "forward_url": "",
        "forward_secret": "",
    }
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ConnectorRegistrationHttpError) as excinfo:
            await post_register_product_payload(
                connector_url="https://connector.example.test",
                admin_key="admin-key",
                payload=payload,
                client=client,
            )
    msg = str(excinfo.value)
    assert "Could not reach the connector" in msg
    assert "https://connector.example.test" in msg
    assert "onboard_product" in msg.lower() or "connector_url" in msg.lower()
    assert "connector host" in msg.lower()
    assert excinfo.value.__cause__ is not None
    assert isinstance(excinfo.value.__cause__, httpx.RequestError)
