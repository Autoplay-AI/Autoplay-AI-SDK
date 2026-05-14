"""Tests for ``proactive_intercom`` JSON parsing.

Covers both the legacy single-dict format (v1) and the new list format (v2).
``ProactiveIntercomMessageRow`` now uses ``user_tour_exists`` / ``user_tour_id``
as the field names; ``offers_tour`` and ``flow_id`` are back-compat properties.
"""

from __future__ import annotations

from autoplay_sdk.proactive_triggers.proactive_intercom_config import (
    TOUR_OFFER_QUICK_REPLY_BODY,
    ProactiveIntercomMessageRow,
    effective_tour_flow_id_for_row,
    parse_proactive_intercom_messages,
    parse_proactive_trigger_configs,
    quick_reply_labels_from_messages_config,
    resolve_tour_offer_for_inbound,
    tour_offer_quick_reply_body,
)


# ---------------------------------------------------------------------------
# Legacy single-dict format (v1) — back-compat
# ---------------------------------------------------------------------------


def test_parse_messages_none_when_missing() -> None:
    assert parse_proactive_intercom_messages({}) is None
    assert parse_proactive_intercom_messages({"proactive_intercom": {}}) is None


def test_parse_messages_orders_labels_legacy_field_names() -> None:
    """Parser still accepts the old ``offers_tour`` / ``flow_id`` key names."""
    cfg = {
        "proactive_intercom": {
            "messages": [
                {
                    "id": "a",
                    "label": "First chip",
                    "offers_tour": True,
                    "flow_id": "flow_a",
                },
                {"id": "b", "label": "Second", "offers_tour": False},
            ]
        }
    }
    rows = parse_proactive_intercom_messages(cfg)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0].label == "First chip"
    # Back-compat properties still work
    assert rows[0].offers_tour is True
    assert rows[0].flow_id == "flow_a"
    # New field names also work
    assert rows[0].user_tour_exists is True
    assert rows[0].user_tour_id == "flow_a"
    labs = quick_reply_labels_from_messages_config(cfg)
    assert labs == ("First chip", "Second")


def test_parse_messages_v2_field_names() -> None:
    """Parser accepts new ``user_tour_exists`` / ``user_tour_id`` keys."""
    cfg = {
        "proactive_intercom": {
            "messages": [
                {
                    "id": "a",
                    "label": "First chip",
                    "user_tour_exists": True,
                    "user_tour_id": "flow_v2",
                },
            ]
        }
    }
    rows = parse_proactive_intercom_messages(cfg)
    assert rows is not None
    assert rows[0].user_tour_exists is True
    assert rows[0].user_tour_id == "flow_v2"


# ---------------------------------------------------------------------------
# New list format (v2)
# ---------------------------------------------------------------------------


def test_parse_proactive_trigger_configs_from_list() -> None:
    cfg = {
        "proactive_intercom": [
            {
                "id": "trig_001",
                "name": "Projects page three chip",
                "proactive_criteria": {
                    "id": "url_change",
                    "name": "URL change",
                    "type": "url_change",
                },
                "messages": [
                    {
                        "id": "chip_1",
                        "label": "Need help?",
                        "user_tour_exists": False,
                    }
                ],
            }
        ]
    }
    configs = parse_proactive_trigger_configs(cfg)
    assert len(configs) == 1
    assert configs[0].id == "trig_001"
    assert len(configs[0].messages) == 1


def test_parse_proactive_trigger_configs_empty_when_not_list() -> None:
    assert parse_proactive_trigger_configs({}) == []
    assert parse_proactive_trigger_configs({"proactive_intercom": {}}) == []


def test_parse_messages_flattens_list_format() -> None:
    """``parse_proactive_intercom_messages`` flattens list-format configs."""
    cfg = {
        "proactive_intercom": [
            {
                "id": "trig_1",
                "name": "T1",
                "proactive_criteria": {"id": "c", "name": "C", "type": "t"},
                "messages": [
                    {"id": "m1", "label": "Label 1", "user_tour_exists": False},
                    {"id": "m2", "label": "Label 2", "user_tour_exists": False},
                ],
            }
        ]
    }
    rows = parse_proactive_intercom_messages(cfg)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0].label == "Label 1"


# ---------------------------------------------------------------------------
# effective_tour_flow_id_for_row — uses new field names
# ---------------------------------------------------------------------------


def test_effective_tour_flow_defaults_when_empty_tour_id() -> None:
    row = ProactiveIntercomMessageRow(
        id="x",
        label="L",
        user_tour_exists=True,
        user_tour_id=None,
    )
    assert effective_tour_flow_id_for_row(row, default_flow_id="def_flow") == "def_flow"


def test_effective_tour_none_when_not_offered() -> None:
    row = ProactiveIntercomMessageRow(
        id="x",
        label="L",
        user_tour_exists=False,
        user_tour_id="fid",
    )
    assert effective_tour_flow_id_for_row(row, default_flow_id="def") is None


def test_effective_tour_explicit_id_takes_priority() -> None:
    row = ProactiveIntercomMessageRow(
        id="x",
        label="L",
        user_tour_exists=True,
        user_tour_id="explicit_flow",
    )
    assert (
        effective_tour_flow_id_for_row(row, default_flow_id="default_flow")
        == "explicit_flow"
    )


# ---------------------------------------------------------------------------
# tour_offer_quick_reply_body
# ---------------------------------------------------------------------------


def test_tour_offer_body_default() -> None:
    assert tour_offer_quick_reply_body(None) == TOUR_OFFER_QUICK_REPLY_BODY
    assert tour_offer_quick_reply_body({}) == TOUR_OFFER_QUICK_REPLY_BODY


def test_tour_offer_body_override() -> None:
    cfg = {"tour_offer_body": "Want a guided walkthrough?"}
    assert tour_offer_quick_reply_body(cfg) == "Want a guided walkthrough?"


def test_tour_offer_body_blank_override_falls_back_to_default() -> None:
    assert (
        tour_offer_quick_reply_body({"tour_offer_body": ""})
        == TOUR_OFFER_QUICK_REPLY_BODY
    )
    assert (
        tour_offer_quick_reply_body({"tour_offer_body": "   "})
        == TOUR_OFFER_QUICK_REPLY_BODY
    )


# ---------------------------------------------------------------------------
# resolve_tour_offer_for_inbound
# ---------------------------------------------------------------------------


def _v2_config(*, user_tour_exists: bool, user_tour_id: str = "flow_abc") -> dict:
    return {
        "proactive_intercom": [
            {
                "id": "trig_1",
                "name": "T1",
                "proactive_criteria": {"id": "c", "name": "C", "type": "t"},
                "messages": [
                    {
                        "id": "chip_1",
                        "label": "Create new project",
                        "user_tour_exists": user_tour_exists,
                        "user_tour_id": user_tour_id,
                    }
                ],
            }
        ]
    }


def test_resolve_tour_offer_returns_flow_id_when_chip_matched() -> None:
    cfg = _v2_config(user_tour_exists=True, user_tour_id="flow_xyz")
    result = resolve_tour_offer_for_inbound(cfg, "Create new project")
    assert result == "flow_xyz"


def test_resolve_tour_offer_returns_none_when_no_tour() -> None:
    cfg = _v2_config(user_tour_exists=False)
    result = resolve_tour_offer_for_inbound(cfg, "Create new project")
    assert result is None


def test_resolve_tour_offer_returns_none_when_chip_not_matched() -> None:
    cfg = _v2_config(user_tour_exists=True)
    result = resolve_tour_offer_for_inbound(cfg, "Something completely different")
    assert result is None


def test_resolve_tour_offer_falls_back_to_default_flow_id() -> None:
    cfg = {
        "proactive_intercom": [
            {
                "id": "trig_1",
                "name": "T1",
                "proactive_criteria": {"id": "c", "name": "C", "type": "t"},
                "messages": [
                    {
                        "id": "chip_1",
                        "label": "Access API key",
                        "user_tour_exists": True,
                    }
                ],
            }
        ]
    }
    result = resolve_tour_offer_for_inbound(
        cfg, "Access API key", default_flow_id="default_flow"
    )
    assert result == "default_flow"


def test_resolve_tour_offer_returns_none_when_no_config() -> None:
    assert resolve_tour_offer_for_inbound(None, "any message") is None
    assert resolve_tour_offer_for_inbound({}, "any message") is None
