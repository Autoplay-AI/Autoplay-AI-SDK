"""Tests for PostHog destination creation (HTTP mocked with respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from autoplay_sdk.providers import PostHogProvider
from autoplay_sdk.providers.posthog.destination import (
    DestinationResult,
    DestinationStatus,
    PostHogDestinationError,
    build_destination_body,
    check_destination_status,
    create_or_update_destination,
)

HOST = "https://us.posthog.com"
PROJECT = "12345"
BASE = f"{HOST}/api/environments/{PROJECT}/hog_functions"

KW = {
    "host": HOST,
    "project_id": PROJECT,
    "personal_api_key": "phx_secret",
    "webhook_url": "https://conn.example.com/webhook/12345",
    "webhook_secret": "whsec_abc",
}


def test_build_body_ships_verbatim_hog_and_inputs() -> None:
    body = build_destination_body(webhook_url="u", webhook_secret="s")
    assert body["type"] == "destination"
    assert body["name"] == "Autoplay Event Stream"
    # The load-bearing Hog source is shipped verbatim, not improvised.
    assert "extractFromElementsChain" in body["hog"]
    assert body["inputs"]["url"]["value"] == "u"
    assert body["inputs"]["headers"]["value"]["x-posthog-secret"] == "s"
    assert body["enabled"] is True


@respx.mock
async def test_creates_new_when_none_exists() -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json={"results": []}))
    post = respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": "new1"}))
    result = await create_or_update_destination(**KW)
    assert result == DestinationResult(id="new1", created=True)
    assert post.called


@respx.mock
async def test_updates_existing_destination() -> None:
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "ex9", "name": "Autoplay Event Stream"}]},
        )
    )
    patch = respx.patch(f"{BASE}/ex9").mock(
        return_value=httpx.Response(200, json={"id": "ex9"})
    )
    result = await create_or_update_destination(**KW)
    assert result == DestinationResult(id="ex9", created=False)
    assert patch.called


@respx.mock
async def test_auth_error_raises_and_redacts_secret() -> None:
    respx.get(BASE).mock(return_value=httpx.Response(401, text="bad: whsec_abc leaked"))
    with pytest.raises(PostHogDestinationError) as exc:
        await create_or_update_destination(**KW)
    msg = str(exc.value)
    assert "401" in msg
    assert "whsec_abc" not in msg  # secret redacted
    assert "***" in msg


@respx.mock
async def test_provider_method_delegates() -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": "viaProvider"}))
    result = await PostHogProvider().create_destination(**KW)
    assert result.created is True
    assert result.id == "viaProvider"


@respx.mock
async def test_verify_enabled_destination() -> None:
    respx.get(f"{BASE}/dest1").mock(
        return_value=httpx.Response(200, json={"id": "dest1", "enabled": True})
    )
    status = await check_destination_status(
        host=HOST,
        project_id=PROJECT,
        personal_api_key="phx_secret",
        destination_id="dest1",
    )
    assert status == DestinationStatus(id="dest1", exists=True, enabled=True)
    assert status.ok is True


@respx.mock
async def test_verify_disabled_destination_not_ok() -> None:
    respx.get(f"{BASE}/dest1").mock(
        return_value=httpx.Response(200, json={"id": "dest1", "enabled": False})
    )
    status = await check_destination_status(
        host=HOST,
        project_id=PROJECT,
        personal_api_key="phx_secret",
        destination_id="dest1",
    )
    assert status.exists is True
    assert status.enabled is False
    assert status.ok is False


@respx.mock
async def test_verify_missing_destination() -> None:
    respx.get(f"{BASE}/gone").mock(return_value=httpx.Response(404))
    status = await check_destination_status(
        host=HOST,
        project_id=PROJECT,
        personal_api_key="phx_secret",
        destination_id="gone",
    )
    assert status.exists is False
    assert status.ok is False


@respx.mock
async def test_provider_verify_delegates() -> None:
    respx.get(f"{BASE}/d2").mock(
        return_value=httpx.Response(200, json={"id": "d2", "enabled": True})
    )
    status = await PostHogProvider().verify(
        host=HOST,
        project_id=PROJECT,
        personal_api_key="phx_secret",
        destination_id="d2",
    )
    assert status.ok is True
