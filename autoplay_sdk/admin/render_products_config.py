"""Merge product rows and sync ``PRODUCTS_CONFIG`` to Render via the REST API.

Used when merging product rows and syncing ``PRODUCTS_CONFIG`` to Render during
operator onboarding. Keeps ``RENDER_API_KEY`` out of the connector service
process — only operator machines / CI should import this.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from autoplay_sdk.admin.onboarding_constants import (
    DEFAULT_PRODUCTS_CONFIG_MERGE_FILENAME,
    JSON_COMPACT_SEPARATORS,
    PRODUCTS_CONFIG_ENV_VAR,
    render_http_timeout_seconds,
    render_products_config_env_var_url,
)

logger = logging.getLogger(__name__)


def _merge_row_product_id_key(pid: Any) -> str:
    """Normalize ids for durable merge/replace (JSON number vs string)."""
    if pid is None:
        return ""
    return str(pid).strip()


def merge_product_entries(
    products: list[dict[str, Any]], new_entry: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return a new list: all rows whose ``product_id`` differs from ``new_entry``, plus ``new_entry``.

    Comparisons normalize ``product_id`` to trimmed strings so legacy Render rows
    with numeric ``product_id`` still match registration payloads that send
    string IDs — otherwise the old row is kept and ``new_entry`` is appended as
    a duplicate and the PUT can appear to omit ``contact_email``.
    """
    pid_new = _merge_row_product_id_key(new_entry.get("product_id"))
    if not pid_new:
        raise ValueError("new_entry must include product_id")
    kept = [
        p for p in products if _merge_row_product_id_key(p.get("product_id")) != pid_new
    ]
    row = dict(new_entry)
    row["product_id"] = pid_new
    kept.append(row)
    return kept


def parse_products_config_array(raw: str | None) -> list[dict[str, Any]] | None:
    """Parse ``PRODUCTS_CONFIG`` JSON string into a list of product dicts, or None if unusable."""
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [p for p in data if isinstance(p, dict)]


def normalize_products_config_rows_for_render(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return shallow copies with ``contact_email`` set for every row (``""`` if missing).

    All code paths that :func:`serialize_products_config` / Render ``PUT`` should see
    this key so host env JSON matches :class:`ProductConfig` and UIs are not missing
    the field when the source of truth is the stored array.
    """
    out: list[dict[str, Any]] = []
    for row in products:
        if not isinstance(row, dict):
            continue
        d = dict(row)
        if "contact_email" not in d:
            d["contact_email"] = ""
        elif d["contact_email"] is None:
            d["contact_email"] = ""
        else:
            d["contact_email"] = str(d["contact_email"]).strip()
        out.append(d)
    return out


def serialize_products_config(products: list[dict[str, Any]]) -> str:
    """Compact JSON string suitable for a single-line env var value."""
    normalized = normalize_products_config_rows_for_render(products)
    for i, row in enumerate(normalized):
        if isinstance(row, dict) and "contact_email" not in row:
            raise ValueError(
                f"PRODUCTS_CONFIG serialize invariant failed at index {i}: missing contact_email"
            )
    return json.dumps(normalized, separators=JSON_COMPACT_SEPARATORS)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def fetch_products_config_from_render(
    *,
    api_key: str,
    service_id: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]] | None:
    """Return parsed ``PRODUCTS_CONFIG`` array from Render, or None if missing/unreadable."""
    own_client = client is None
    timeout = render_http_timeout_seconds()
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        url = render_products_config_env_var_url(service_id)
        resp = await c.get(url, headers=_auth_headers(api_key))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        raw_val: str | None = None
        if isinstance(body, dict):
            ev = body.get("envVar") or body
            if isinstance(ev, dict):
                raw_val = ev.get("value")
        if raw_val is None:
            return None
        parsed = parse_products_config_array(str(raw_val))
        if parsed is None:
            logger.warning(
                "render_products_config: %s from Render was not a JSON array",
                PRODUCTS_CONFIG_ENV_VAR,
            )
        return parsed
    except httpx.HTTPError as exc:
        logger.warning(
            "render_products_config: GET %s failed: %s", PRODUCTS_CONFIG_ENV_VAR, exc
        )
        return None
    finally:
        if own_client:
            await c.aclose()


async def put_products_config_on_render(
    *,
    api_key: str,
    service_id: str,
    products: list[dict[str, Any]],
    client: httpx.AsyncClient | None = None,
) -> None:
    """Set ``PRODUCTS_CONFIG`` on the Render service to the serialized array."""
    own_client = client is None
    timeout = render_http_timeout_seconds()
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        url = render_products_config_env_var_url(service_id)
        payload = {"value": serialize_products_config(products)}
        resp = await c.put(url, headers=_auth_headers(api_key), json=payload)
        resp.raise_for_status()
    finally:
        if own_client:
            await c.aclose()


def load_merge_base_from_local(path: Path) -> list[dict[str, Any]] | None:
    """Load JSON array from ``path`` if it exists; return None if missing or invalid."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "render_products_config: could not read merge local %s: %s", path, exc
        )
        return None
    if not isinstance(data, list):
        return None
    return [p for p in data if isinstance(p, dict)]


def write_merge_local(path: Path, products: list[dict[str, Any]]) -> None:
    """Persist merged array for the operator (gitignored file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(products, indent=2) + "\n")


async def sync_products_config_to_render(
    *,
    api_key: str,
    service_id: str,
    new_entry: dict[str, Any],
    merge_local_path: Path | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Merge ``new_entry`` into the durable config and PUT ``PRODUCTS_CONFIG`` on Render.

    Merge base order:
    1. ``merge_local_path`` if the file exists (operator source of truth when Render GET is redacted).
    2. Else current value from Render if parseable.
    3. Else empty list.
    """
    base: list[dict[str, Any]] = []
    if merge_local_path and merge_local_path.is_file():
        loaded = load_merge_base_from_local(merge_local_path)
        if loaded is not None:
            base = loaded
    if not base:
        remote = await fetch_products_config_from_render(
            api_key=api_key, service_id=service_id, client=client
        )
        if remote is not None:
            base = remote

    merged = merge_product_entries(base, new_entry)
    await put_products_config_on_render(
        api_key=api_key, service_id=service_id, products=merged, client=client
    )
    if merge_local_path is not None:
        write_merge_local(merge_local_path, merged)
    return merged


def default_merge_local_path() -> Path:
    """Default path for the operator merge file (repo root).

    ``__file__`` is ``.../autoplay_sdk/admin/render_products_config.py``;
    ``parents[2]`` is the repo root.
    """
    return Path(__file__).resolve().parents[2] / DEFAULT_PRODUCTS_CONFIG_MERGE_FILENAME
