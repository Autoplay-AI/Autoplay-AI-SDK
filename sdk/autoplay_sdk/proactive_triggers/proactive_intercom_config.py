"""Parse ``integration_config.proactive_intercom`` for Intercom chip tours.

``proactive_intercom`` is now a **list** of :class:`ProactiveTriggerConfig` objects
(v2 format).  The legacy single-dict format (with a ``messages`` key) is still
supported via back-compat helpers so existing configs do not break on deploy.

v2 field names
--------------
- ``user_tour_exists`` (was ``offers_tour``)
- ``user_tour_id``     (was ``flow_id``)

Back-compat: both old and new field names are accepted when parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from autoplay_sdk.proactive_triggers.quick_reply_match import match_quick_reply_label
from autoplay_sdk.proactive_triggers.tour_registry import TourRegistry
from autoplay_sdk.proactive_triggers.trigger_config import (
    ProactiveTriggerConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy row dataclass (back-compat with existing connector call sites)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProactiveIntercomMessageRow:
    """One proactive chip row from host JSON.

    Field names follow the v2 convention (``user_tour_exists``, ``user_tour_id``).
    The parser accepts both old names (``offers_tour``, ``flow_id``) and new names.
    """

    id: str
    label: str
    user_tour_exists: bool
    user_tour_id: str | None

    # Back-compat properties so call sites using the old names still work.
    @property
    def offers_tour(self) -> bool:
        return self.user_tour_exists

    @property
    def flow_id(self) -> str | None:
        return self.user_tour_id


def _parse_message_row(row: dict, index: int) -> ProactiveIntercomMessageRow | None:
    """Parse one chip row dict, accepting both v1 and v2 field names."""
    if not isinstance(row, dict):
        return None
    mid = str(row.get("id") or f"msg_{index}").strip()
    label = str(row.get("label") or "").strip()
    if not label:
        return None
    # v2 name takes priority; fall back to v1 name
    user_tour_exists = bool(
        row.get("user_tour_exists")
        if "user_tour_exists" in row
        else row.get("offers_tour")
    )
    fid_raw = row.get("user_tour_id") if "user_tour_id" in row else row.get("flow_id")
    fid = str(fid_raw).strip() if fid_raw is not None else ""
    return ProactiveIntercomMessageRow(
        id=mid or f"msg_{index}",
        label=label,
        user_tour_exists=user_tour_exists,
        user_tour_id=fid or None,
    )


# ---------------------------------------------------------------------------
# v2: proactive_intercom is a list of ProactiveTriggerConfig
# ---------------------------------------------------------------------------


def parse_proactive_trigger_configs(
    integration_config: dict[str, Any] | None,
) -> list[ProactiveTriggerConfig]:
    """Parse ``integration_config.proactive_intercom`` as a list of trigger configs.

    Returns an empty list when the key is absent, not a list, or every entry
    fails to parse (errors are logged at WARNING and skipped).
    """
    cfg = integration_config or {}
    raw = cfg.get("proactive_intercom")
    if not isinstance(raw, list):
        return []
    out: list[ProactiveTriggerConfig] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning(
                "proactive_intercom[%d]: expected dict, got %s — skipping",
                i,
                type(entry).__name__,
                extra={
                    "event_type": "proactive_trigger_config_invalid_type",
                    "index": i,
                    "got_type": type(entry).__name__,
                },
            )
            continue
        try:
            out.append(ProactiveTriggerConfig.from_dict(entry))
        except Exception as exc:
            logger.warning(
                "proactive_intercom[%d]: failed to parse ProactiveTriggerConfig — skipping: %s",
                i,
                exc,
                exc_info=True,
                extra={
                    "event_type": "proactive_trigger_config_parse_error",
                    "index": i,
                },
            )
    return out


def find_trigger_config_by_criteria(
    configs: list[ProactiveTriggerConfig],
    criteria_id: str,
) -> ProactiveTriggerConfig | None:
    """Return the first config whose top-level ``proactive_criteria.id`` matches."""
    for cfg in configs:
        if cfg.proactive_criteria.id == criteria_id:
            return cfg
    return None


# ---------------------------------------------------------------------------
# Legacy helpers: parse from old single-dict proactive_intercom.messages format
# ---------------------------------------------------------------------------


def parse_proactive_intercom_messages(
    integration_config: dict[str, Any] | None,
) -> tuple[ProactiveIntercomMessageRow, ...] | None:
    """Return chip rows from the legacy single-dict format, or ``None``.

    Supports both old field names (``offers_tour``, ``flow_id``) and new names
    (``user_tour_exists``, ``user_tour_id``).

    When ``proactive_intercom`` is a list (v2 format), flattens messages from
    all configs into one tuple so legacy call sites keep working.
    """
    cfg = integration_config or {}
    inter = cfg.get("proactive_intercom")

    # v2 list format — flatten all messages across all trigger configs
    if isinstance(inter, list):
        out: list[ProactiveIntercomMessageRow] = []
        for entry in inter:
            if not isinstance(entry, dict):
                continue
            for i, row in enumerate(entry.get("messages") or []):
                parsed = _parse_message_row(row, i)
                if parsed is not None:
                    out.append(parsed)
        return tuple(out) if out else None

    # Legacy single-dict format
    if not isinstance(inter, dict):
        return None
    raw_messages = inter.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None
    out = []
    for i, row in enumerate(raw_messages):
        parsed = _parse_message_row(row, i)
        if parsed is not None:
            out.append(parsed)
    return tuple(out) if out else None


def quick_reply_labels_from_messages_config(
    integration_config: dict[str, Any] | None,
) -> tuple[str, ...] | None:
    """Ordered chip labels from JSON, or ``None`` to fall back to code defaults."""
    rows = parse_proactive_intercom_messages(integration_config)
    if not rows:
        return None
    return tuple(r.label for r in rows)


def effective_tour_flow_id_for_row(
    row: ProactiveIntercomMessageRow,
    *,
    default_flow_id: str,
) -> str | None:
    """Return UserTour flow id when this row offers a tour, else ``None``."""
    if not row.user_tour_exists:
        return None
    explicit = (row.user_tour_id or "").strip()
    base = (default_flow_id or "").strip()
    return explicit or base


TOUR_OFFER_QUICK_REPLY_BODY = "Would you like me to show you?"


def tour_offer_quick_reply_body(
    integration_config: dict[str, Any] | None = None,
) -> str:
    """Return the body text for the tour-offer Yes/No message.

    Reads ``integration_config.tour_offer_body`` so each product can override the
    default "Would you like me to show you?" wording.  Falls back to the SDK
    default when the key is absent or blank.

    This is the single SDK source-of-truth for the tour-offer message body — call
    it from any chatbot connector (Intercom, Ada, etc.) after the LLM reply when
    ``resolve_tour_offer_for_inbound`` returns a non-None flow id.
    """
    cfg = integration_config or {}
    raw = (cfg.get("tour_offer_body") or "").strip()
    return raw or TOUR_OFFER_QUICK_REPLY_BODY


def resolve_tour_offer_for_inbound(
    integration_config: dict[str, Any] | None,
    user_message: str,
    *,
    default_flow_id: str = "",
) -> str | None:
    """Return the tour flow id if user_message matches a chip with user_tour_exists=True.

    This is the single entry point for the tour-offer decision. Any product whose
    chip config has ``user_tour_exists: true`` will automatically trigger the
    Yes/No tour offer after the LLM reply — no product-ID gate needed in call sites.

    Returns ``None`` when:
    - the product has no messages config
    - the message does not match any chip label
    - the matched chip has ``user_tour_exists=False``
    """
    rows = parse_proactive_intercom_messages(integration_config)
    if rows is None:
        return None
    _idx, row = match_message_row_by_inbound_text(rows, user_message)
    if row is None:
        return None
    return effective_tour_flow_id_for_row(row, default_flow_id=default_flow_id)


def parse_tour_registry(
    integration_config: dict[str, Any] | None,
    product_id: str = "",
) -> TourRegistry | None:
    """Parse ``integration_config.tour_registry`` into a :class:`TourRegistry`.

    Returns ``None`` when the key is absent or is not a list.
    The ``product_id`` argument is used to label the registry for logging.
    """
    cfg = integration_config or {}
    raw = cfg.get("tour_registry")
    if not isinstance(raw, list):
        return None
    registry_dict = {
        "product_id": product_id,
        "tours": raw,
    }
    try:
        return TourRegistry.from_dict(registry_dict)
    except Exception as exc:
        logger.warning(
            "tour_registry: failed to parse — %s",
            exc,
            exc_info=True,
            extra={
                "event_type": "tour_registry_parse_error",
                "product_id": product_id,
            },
        )
        return None


def match_message_row_by_inbound_text(
    rows: tuple[ProactiveIntercomMessageRow, ...],
    user_message: str,
) -> tuple[int | None, ProactiveIntercomMessageRow | None]:
    """Match inbound Intercom text to a configured row (same normalization as chip matching)."""
    labels = tuple(r.label for r in rows)
    idx = match_quick_reply_label(user_message, labels)
    if idx is None:
        return None, None
    return idx, rows[idx]
