"""Env names and timeouts for operator onboarding (Render + connector HTTP).

Duplicated from ``event_connector.constants`` so ``autoplay_sdk`` does not depend
on ``event_connector``. The connector re-exports ``render_products_config_env_var_url``
from here via ``event_connector.constants`` for backward compatibility.
"""

from __future__ import annotations

import os
from typing import Final
from urllib.parse import quote

PRODUCTS_CONFIG_ENV_VAR: Final[str] = "PRODUCTS_CONFIG"
PRODUCTS_CONFIG_DEFAULT_JSON: Final[str] = "[]"

JSON_COMPACT_SEPARATORS: Final[tuple[str, str]] = (",", ":")

RENDER_API_KEY_ENV_VAR: Final[str] = "RENDER_API_KEY"
RENDER_SERVICE_ID_ENV_VAR: Final[str] = "RENDER_SERVICE_ID"
PRODUCTS_CONFIG_MERGE_LOCAL_ENV_VAR: Final[str] = "PRODUCTS_CONFIG_MERGE_LOCAL"

RENDER_API_BASE_URL_ENV_VAR: Final[str] = "RENDER_API_BASE_URL"
DEFAULT_RENDER_API_BASE_URL: Final[str] = "https://api.render.com/v1"

RENDER_HTTP_TIMEOUT_SECONDS_ENV_VAR: Final[str] = "RENDER_HTTP_TIMEOUT_SECONDS"
_DEFAULT_RENDER_HTTP_TIMEOUT: Final[float] = 60.0
_MIN_RENDER_HTTP_TIMEOUT: Final[float] = 5.0
_MAX_RENDER_HTTP_TIMEOUT: Final[float] = 300.0

DEFAULT_PRODUCTS_CONFIG_MERGE_FILENAME: Final[str] = "products.config.local.json"

ONBOARD_CONNECTOR_TIMEOUT_ENV_VAR: Final[str] = "ONBOARD_CONNECTOR_TIMEOUT_SECONDS"
_DEFAULT_ONBOARD_CONNECTOR_TIMEOUT: Final[float] = 15.0
_MIN_ONBOARD_CONNECTOR_TIMEOUT: Final[float] = 1.0
_MAX_ONBOARD_CONNECTOR_TIMEOUT: Final[float] = 120.0


def onboard_connector_http_timeout_seconds() -> float:
    """Timeout for ``POST /products`` from onboarding clients."""
    raw = os.environ.get(
        ONBOARD_CONNECTOR_TIMEOUT_ENV_VAR,
        str(int(_DEFAULT_ONBOARD_CONNECTOR_TIMEOUT)),
    ).strip()
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_ONBOARD_CONNECTOR_TIMEOUT
    return max(
        _MIN_ONBOARD_CONNECTOR_TIMEOUT, min(value, _MAX_ONBOARD_CONNECTOR_TIMEOUT)
    )


def render_api_base_url() -> str:
    """Render REST API origin (no trailing slash)."""
    return os.environ.get(
        RENDER_API_BASE_URL_ENV_VAR, DEFAULT_RENDER_API_BASE_URL
    ).rstrip("/")


def render_http_timeout_seconds() -> float:
    """HTTP client timeout for Render API calls; clamped for sanity."""
    raw = os.environ.get(
        RENDER_HTTP_TIMEOUT_SECONDS_ENV_VAR,
        str(int(_DEFAULT_RENDER_HTTP_TIMEOUT)),
    ).strip()
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_RENDER_HTTP_TIMEOUT
    return max(_MIN_RENDER_HTTP_TIMEOUT, min(value, _MAX_RENDER_HTTP_TIMEOUT))


def render_products_config_env_var_url(service_id: str) -> str:
    """URL for GET/PUT a single env var on a Render web service."""
    key_enc = quote(PRODUCTS_CONFIG_ENV_VAR, safe="")
    return f"{render_api_base_url()}/services/{service_id}/env-vars/{key_enc}"
