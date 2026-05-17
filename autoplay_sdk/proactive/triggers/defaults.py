"""Central defaults for proactive triggers (transport-agnostic detection layer).

``trigger_id`` strings are **code-defined** (not environment-driven) so analytics,
cooldown keys, and logs stay stable across processes and deployments. Override
IDs only via new SDK versions or explicit application-level mapping — not ad-hoc
env vars — unless you intentionally migrate metrics and stored keys.

Quick-reply **copy** defaults live here too; :mod:`autoplay_sdk.integrations.intercom`
re-exports them under ``INTERCOM_*`` names for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProactiveTriggerIds:
    """Stable identifiers for built-in triggers — single registry."""

    canonical_ping_pong: str = "canonical_url_ping_pong"
    user_page_dwell: str = "user_page_dwell"
    section_playbook_match: str = "section_playbook_match"


PROACTIVE_TRIGGER_IDS = ProactiveTriggerIds()


def get_proactive_trigger_ids() -> ProactiveTriggerIds:
    """Return the shared trigger id registry."""
    return PROACTIVE_TRIGGER_IDS


TRIGGER_ID_CANONICAL_URL_PING_PONG = PROACTIVE_TRIGGER_IDS.canonical_ping_pong
TRIGGER_ID_USER_PAGE_DWELL = PROACTIVE_TRIGGER_IDS.user_page_dwell
TRIGGER_ID_SECTION_PLAYBOOK_MATCH = PROACTIVE_TRIGGER_IDS.section_playbook_match

DEFAULT_PROACTIVE_QUICK_REPLY_BODY = "Need my expert help?"
