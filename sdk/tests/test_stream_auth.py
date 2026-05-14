"""SSE Bearer resolution via ``AUTOPLAY_APP_UNKEY_TOKEN``."""

from __future__ import annotations

import pytest

from autoplay_sdk.async_client import AsyncConnectorClient
from autoplay_sdk.client import ConnectorClient
from autoplay_sdk.stream_auth import resolve_connector_bearer_token


def test_resolve_explicit_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOPLAY_APP_UNKEY_TOKEN", "from_env")
    assert resolve_connector_bearer_token("  explicit  ") == "explicit"


def test_resolve_env_when_explicit_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOPLAY_APP_UNKEY_TOKEN", "from_env")
    assert resolve_connector_bearer_token("") == "from_env"
    assert resolve_connector_bearer_token("   ") == "from_env"


def test_connector_client_uses_env_when_token_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOPLAY_APP_UNKEY_TOKEN", "env_token")
    client = ConnectorClient(url="http://x")
    assert client._token == "env_token"


def test_async_connector_client_uses_env_when_token_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOPLAY_APP_UNKEY_TOKEN", "env_token")
    client = AsyncConnectorClient(url="http://x")
    assert client._token == "env_token"
