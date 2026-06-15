"""Create (or update) the Autoplay PostHog ``hog_function`` destination.

This is the deterministic, code-path replacement for the agent-driven "Step 4"
in the old setup skill: given the webhook URL + secret returned by
``onboard_product``, it creates the "Autoplay Event Stream" destination in
PostHog via the API — idempotently (reuse + update if it already exists).

The Hog source is shipped verbatim as ``autoplay_destination.hog`` (it is
load-bearing — from the Autoplay quickstart docs — so it is never hand-edited).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import httpx

DESTINATION_NAME = "Autoplay Event Stream"
_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class DestinationResult:
    """Outcome of creating/updating the destination.

    Attributes:
        id: The PostHog hog_function id.
        created: True if newly created; False if an existing one was updated.
    """

    id: str
    created: bool


@dataclass(frozen=True)
class DestinationStatus:
    """Provider-specific verification result for a PostHog destination.

    Attributes:
        id: The hog_function id checked.
        exists: True if PostHog still has this destination.
        enabled: True if the destination is enabled (events will be forwarded).
    """

    id: str
    exists: bool
    enabled: bool

    @property
    def ok(self) -> bool:
        """True when the destination exists and is enabled."""
        return self.exists and self.enabled


class PostHogDestinationError(Exception):
    """Creating or updating the PostHog destination failed."""


def _load_hog_source() -> str:
    """Return the verbatim Hog source shipped alongside this module."""
    return (
        resources.files("autoplay_sdk.providers.posthog")
        .joinpath("autoplay_destination.hog")
        .read_text(encoding="utf-8")
    )


def build_destination_body(
    *, webhook_url: str, webhook_secret: str, name: str = DESTINATION_NAME
) -> dict:
    """Build the hog_function request body PostHog's API expects.

    ``inputs_schema`` is required — PostHog validates ``inputs`` against it.
    """
    return {
        "type": "destination",
        "name": name,
        "hog": _load_hog_source(),
        "inputs": {
            "url": {"value": webhook_url},
            "headers": {"value": {"x-posthog-secret": webhook_secret}},
            "debug": {"value": False},
        },
        "inputs_schema": [
            {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
            {
                "key": "headers",
                "type": "dictionary",
                "label": "Headers",
                "required": False,
            },
            {
                "key": "debug",
                "type": "boolean",
                "label": "Debug",
                "required": False,
                "default": False,
            },
        ],
        "enabled": True,
        "filters": {},
    }


async def create_or_update_destination(
    *,
    host: str,
    project_id: str,
    personal_api_key: str,
    webhook_url: str,
    webhook_secret: str,
    name: str = DESTINATION_NAME,
    client: httpx.AsyncClient | None = None,
) -> DestinationResult:
    """Idempotently create or update the Autoplay destination in PostHog.

    Lists existing hog_functions; if one named ``name`` exists it is PATCHed,
    otherwise a new one is POSTed.

    Args:
        host: PostHog host, e.g. ``https://us.posthog.com``.
        project_id: PostHog project id.
        personal_api_key: Personal API key (``phx_…``) with ``hog_function:write``.
        webhook_url: Connector webhook URL from ``onboard_product``.
        webhook_secret: Connector webhook secret from ``onboard_product``.
        name: Destination name (used as the idempotency key).
        client: Optional injected client (tests); one is created otherwise.

    Returns:
        DestinationResult with the destination id and whether it was created.

    Raises:
        PostHogDestinationError: On any non-2xx PostHog API response.
    """
    base = f"{host.rstrip('/')}/api/environments/{project_id}/hog_functions"
    headers = {"Authorization": f"Bearer {personal_api_key}"}
    body = build_destination_body(
        webhook_url=webhook_url, webhook_secret=webhook_secret, name=name
    )

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        existing_id = await _find_existing_id(
            client, base, headers, name, webhook_secret
        )
        if existing_id is not None:
            resp = await client.patch(
                f"{base}/{existing_id}", headers=headers, json=body
            )
            _raise_for_status(resp, webhook_secret)
            return DestinationResult(id=existing_id, created=False)

        resp = await client.post(base, headers=headers, json=body)
        _raise_for_status(resp, webhook_secret)
        new_id = str(_safe_json(resp).get("id", ""))
        return DestinationResult(id=new_id, created=True)
    finally:
        if owns_client:
            await client.aclose()


async def check_destination_status(
    *,
    host: str,
    project_id: str,
    personal_api_key: str,
    destination_id: str,
    client: httpx.AsyncClient | None = None,
) -> DestinationStatus:
    """Provider-specific verification: is the destination present and enabled?

    Confirms PostHog still has the hog_function and that it's enabled (so events
    will be forwarded). This is a *config* check — it does not by itself prove an
    event was delivered; that end-to-end proof is observed connector-side.

    Args:
        host: PostHog host.
        project_id: PostHog project id.
        personal_api_key: Personal API key (``phx_…``).
        destination_id: The hog_function id from ``create_or_update_destination``.
        client: Optional injected client (tests).

    Returns:
        DestinationStatus (``.ok`` is True when it exists and is enabled).

    Raises:
        PostHogDestinationError: On a non-2xx response other than 404.
    """
    url = (
        f"{host.rstrip('/')}/api/environments/{project_id}"
        f"/hog_functions/{destination_id}"
    )
    headers = {"Authorization": f"Bearer {personal_api_key}"}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return DestinationStatus(id=destination_id, exists=False, enabled=False)
        _raise_for_status(resp, "")
        data = _safe_json(resp)
        return DestinationStatus(
            id=destination_id,
            exists=True,
            enabled=bool(data.get("enabled", False)),
        )
    finally:
        if owns_client:
            await client.aclose()


async def _find_existing_id(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    name: str,
    webhook_secret: str,
) -> str | None:
    """Return the id of an existing destination named ``name``, or None."""
    resp = await client.get(base, headers=headers)
    _raise_for_status(resp, webhook_secret)
    for item in _safe_json(resp).get("results", []):
        if item.get("name") == name:
            return str(item.get("id"))
    return None


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _raise_for_status(resp: httpx.Response, webhook_secret: str) -> None:
    """Raise PostHogDestinationError on >=400, with the secret redacted."""
    if resp.status_code < 400:
        return
    text = resp.text
    if webhook_secret:
        text = text.replace(webhook_secret, "***")
    raise PostHogDestinationError(f"PostHog API {resp.status_code}: {text[:500]}")


__all__ = [
    "DestinationResult",
    "DestinationStatus",
    "PostHogDestinationError",
    "build_destination_body",
    "check_destination_status",
    "create_or_update_destination",
]
