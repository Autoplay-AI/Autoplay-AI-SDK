"""Concrete proactive trigger implementations."""

from autoplay_sdk.proactive_triggers.defaults import (
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
    TRIGGER_ID_SECTION_PLAYBOOK_MATCH,
    TRIGGER_ID_USER_PAGE_DWELL,
)
from autoplay_sdk.proactive_triggers.triggers.canonical_ping_pong import (
    CanonicalPingPongTrigger,
)
from autoplay_sdk.proactive_triggers.triggers.section_playbook import (
    SectionPlaybookTrigger,
)
from autoplay_sdk.proactive_triggers.triggers.user_page_dwell import (
    UserPageDwellTrigger,
)

__all__ = [
    "TRIGGER_ID_CANONICAL_URL_PING_PONG",
    "TRIGGER_ID_SECTION_PLAYBOOK_MATCH",
    "TRIGGER_ID_USER_PAGE_DWELL",
    "CanonicalPingPongTrigger",
    "SectionPlaybookTrigger",
    "UserPageDwellTrigger",
]
