"""Section playbook match — guidance copy from ``section_playbook`` using metrics + overrides."""

from __future__ import annotations

from typing import Any

from autoplay_sdk.proactive_triggers.defaults import TRIGGER_ID_SECTION_PLAYBOOK_MATCH
from autoplay_sdk.proactive_triggers.judge import validate_or_truncate_proactive_body
from autoplay_sdk.proactive_triggers.section_activity import (
    resolve_section_id_for_playbook,
)
from autoplay_sdk.proactive_triggers.types import (
    ProactiveTriggerContext,
    ProactiveTriggerResult,
)


class SectionPlaybookTrigger:
    """Resolve ``section_playbook`` row using ``product_section_playbook`` + precedence."""

    @property
    def trigger_id(self) -> str:
        return TRIGGER_ID_SECTION_PLAYBOOK_MATCH

    def evaluate(self, ctx: ProactiveTriggerContext) -> ProactiveTriggerResult | None:
        extra: dict[str, Any] = ctx.context_extra or {}
        book = extra.get("section_playbook")
        if not isinstance(book, dict):
            return None

        section_id = resolve_section_id_for_playbook(extra)
        if not section_id:
            return None

        row = book.get(section_id)
        if row is None:
            return None
        if isinstance(row, str):
            body = row.strip()
            labels: tuple[str, ...] = ()
        elif isinstance(row, dict):
            body = (row.get("body") or row.get("proactive_body") or "").strip()
            raw_labels = row.get("reply_option_labels") or row.get("quick_reply_labels")
            if isinstance(raw_labels, (list, tuple)):
                labels = tuple(str(x) for x in raw_labels if str(x).strip())
            else:
                labels = ()
        else:
            return None
        if not body:
            return None
        body = validate_or_truncate_proactive_body(body)
        meta: dict[str, Any] = {"section_id": section_id}
        return ProactiveTriggerResult(
            trigger_id=self.trigger_id,
            body=body,
            reply_option_labels=labels,
            metadata=meta,
        )
