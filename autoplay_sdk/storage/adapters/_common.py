"""Shared helpers for the write-only analytics sink adapters.

Sinks operate on the JSON wire dicts (a model's ``to_dict()``), not the typed
models, and are best-effort: a telemetry failure logs a warning and never
raises into the fan-out loop.
"""

from __future__ import annotations

import logging
from typing import Any

from autoplay_sdk.user_adoption_state import WorkflowStatus

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 10.0


def workflow_ids_by_status(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Derive (completed, in_progress) workflow ids from a user-state dict.

    The user-state document stores the full ``onboarding.workflow_progress`` map
    rather than pre-split id lists, so we project it here.
    """
    onboarding = state.get("onboarding") or {}
    progress = onboarding.get("workflow_progress") or {}
    completed: list[str] = []
    in_progress: list[str] = []
    if isinstance(progress, dict):
        for wid, wp in progress.items():
            if not isinstance(wp, dict):
                continue
            status = wp.get("status")
            if status == WorkflowStatus.COMPLETED.value:
                completed.append(str(wid))
            elif status == WorkflowStatus.IN_PROGRESS.value:
                in_progress.append(str(wid))
    return completed, in_progress


async def best_effort_post(
    url: str,
    payload: dict[str, Any],
    *,
    label: str,
    client: Any | None = None,
) -> None:
    """POST ``payload`` to ``url`` as JSON, swallowing+logging any failure.

    ``client`` is an optional injected ``httpx.AsyncClient`` (tests); otherwise
    one is created per call. ``httpx`` is imported lazily so importing a sink
    module stays cheap.
    """
    import httpx

    try:
        if client is not None:
            resp = await client.post(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as owned:
                resp = await owned.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001 — telemetry is best-effort
        logger.warning("%s: post failed: %s", label, exc)
        return
    status = getattr(resp, "status_code", 0)
    if status >= 400:
        logger.warning("%s: non-2xx response %s", label, status)


__all__ = ["workflow_ids_by_status", "best_effort_post"]
