"""autoplay_sdk.storage.adapters.posthog — write-only PostHog sink.

Mirrors user state into PostHog person properties (via ``$set``) and each frozen
session into an ``autoplay_session_captured`` event. Read methods return
``None`` — PostHog is a write-only destination; reads are served by the primary
(Redis) adapter. Customers read the data back from their own PostHog project.

Best-effort: a failed POST is logged, never raised, so a PostHog outage never
blocks the primary write.

Needs the ``analytics`` extra::

    pip install "autoplay-sdk[analytics]"
"""

from __future__ import annotations

from typing import Any

from autoplay_sdk.storage.adapters._common import (
    best_effort_post,
    workflow_ids_by_status,
)
from autoplay_sdk.storage.base import AutoplayStorageAdapter

_DEFAULT_HOST = "https://app.posthog.com"
_SESSION_EVENT = "autoplay_session_captured"


class PostHogStorageAdapter(AutoplayStorageAdapter):
    """Write-only PostHog destination for user state + session snapshots.

    Args:
        api_key: PostHog project API key.
        host: PostHog host (override for self-hosted / EU cloud).
        property_prefix: Optional namespace for person properties. ``"ap"`` ->
            ``ap_journey_state``; default (empty) -> ``journey_state``.
        client: Optional injected ``httpx.AsyncClient`` (tests).
    """

    def __init__(
        self,
        api_key: str,
        *,
        host: str = _DEFAULT_HOST,
        property_prefix: str = "",
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.host = host.rstrip("/")
        self._client = client
        self._p = f"{property_prefix}_" if property_prefix else ""

    @property
    def _capture_url(self) -> str:
        return f"{self.host}/capture/"

    def _key(self, name: str) -> str:
        return f"{self._p}{name}"

    async def save_user_state(
        self, product_id: str, user_id: str, state: dict[str, Any]
    ) -> None:
        onboarding = state.get("onboarding") or {}
        mastery = state.get("mastery") or {}
        sessions = state.get("sessions") or {}
        completed, in_progress = workflow_ids_by_status(state)
        payload = {
            "api_key": self.api_key,
            "distinct_id": user_id,
            "event": "$set",
            "properties": {
                "$set": {
                    self._key("product_id"): product_id,
                    self._key("journey_state"): state.get("journey_state"),
                    self._key("mastery_level"): mastery.get("level"),
                    self._key("mastery_rating"): mastery.get("rating"),
                    self._key("is_onboarded"): onboarding.get("onboarding_completed_at")
                    is not None,
                    self._key("onboarding_summary"): onboarding.get("summary"),
                    self._key("completion_rate"): onboarding.get("completion_rate"),
                    self._key("session_count"): sessions.get("count"),
                    self._key("completed_workflows"): completed,
                    self._key("in_progress_workflows"): in_progress,
                }
            },
        }
        await best_effort_post(
            self._capture_url,
            payload,
            label="PostHogStorageAdapter",
            client=self._client,
        )

    async def get_user_state(
        self, product_id: str, user_id: str
    ) -> dict[str, Any] | None:
        return None  # write-only: read from PostHog

    async def save_session_snapshot(
        self,
        product_id: str,
        user_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        mastery = snapshot.get("mastery") or {}
        payload = {
            "api_key": self.api_key,
            "distinct_id": user_id,
            "event": _SESSION_EVENT,
            "properties": {
                "product_id": product_id,
                "session_id": session_id,
                "session_number": snapshot.get("session_number"),
                "duration_s": snapshot.get("duration_s"),
                "completion_rate": snapshot.get("completion_rate"),
                "completed_workflow_ids": snapshot.get("completed_workflow_ids"),
                "in_progress_workflow_ids": snapshot.get("in_progress_workflow_ids"),
                "mastery_level": mastery.get("level"),
                "reached_onboarding_complete": snapshot.get(
                    "reached_onboarding_complete"
                ),
            },
        }
        await best_effort_post(
            self._capture_url,
            payload,
            label="PostHogStorageAdapter",
            client=self._client,
        )

    async def get_session_snapshot(
        self, product_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        return None  # write-only: read from PostHog


__all__ = ["PostHogStorageAdapter"]
