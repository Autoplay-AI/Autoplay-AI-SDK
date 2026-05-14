"""Tests for autoplay_sdk.proactive_triggers.trigger_config.

Covers:
- TriggerMessage validation and serialisation
- ProactiveCriteria recursive tree: CriteriaLeaf, CriteriaGroup (AND/OR, nested)
- ProactiveTriggerConfig validation (0 msgs / 4 msgs / 1-3 msgs)
- Full from_dict round-trips including compound criteria trees
"""

from __future__ import annotations

import pytest

from autoplay_sdk.proactive_triggers.trigger_config import (
    CriteriaGroup,
    CriteriaLeaf,
    ProactiveTriggerConfig,
    TriggerMessage,
    criteria_from_dict,
)


# ---------------------------------------------------------------------------
# TriggerMessage
# ---------------------------------------------------------------------------


class TestTriggerMessage:
    def test_no_tour_constructs_fine(self) -> None:
        m = TriggerMessage(id="m1", label="Hello")
        assert m.user_tour_exists is False
        assert m.user_tour_id is None

    def test_tour_with_id_constructs_fine(self) -> None:
        m = TriggerMessage(
            id="m1", label="Hello", user_tour_exists=True, user_tour_id="flow_1"
        )
        assert m.user_tour_id == "flow_1"

    def test_tour_without_id_raises(self) -> None:
        with pytest.raises(ValueError, match="user_tour_id is required"):
            TriggerMessage(id="m1", label="Hello", user_tour_exists=True)

    def test_to_dict_omits_user_tour_id_when_none(self) -> None:
        m = TriggerMessage(id="m1", label="Hello")
        d = m.to_dict()
        assert "user_tour_id" not in d
        assert d["user_tour_exists"] is False

    def test_to_dict_includes_user_tour_id_when_set(self) -> None:
        m = TriggerMessage(
            id="m1", label="Hello", user_tour_exists=True, user_tour_id="flow_1"
        )
        d = m.to_dict()
        assert d["user_tour_id"] == "flow_1"
        assert d["user_tour_exists"] is True

    def test_from_dict_round_trip_no_tour(self) -> None:
        orig = TriggerMessage(id="m1", label="Hi")
        restored = TriggerMessage.from_dict(orig.to_dict())
        assert restored == orig

    def test_from_dict_round_trip_with_tour(self) -> None:
        orig = TriggerMessage(
            id="m2", label="Start tour", user_tour_exists=True, user_tour_id="f1"
        )
        restored = TriggerMessage.from_dict(orig.to_dict())
        assert restored == orig


# ---------------------------------------------------------------------------
# ProactiveCriteria — leaf
# ---------------------------------------------------------------------------


class TestCriteriaLeaf:
    _DICT = {"id": "url_change", "name": "URL change", "type": "url_change"}

    def test_from_dict_produces_leaf(self) -> None:
        leaf = criteria_from_dict(self._DICT)
        assert isinstance(leaf, CriteriaLeaf)
        assert leaf.type == "url_change"

    def test_leaf_to_dict_round_trip(self) -> None:
        leaf = criteria_from_dict(self._DICT)
        assert leaf.to_dict() == self._DICT

    def test_leaf_missing_type_raises(self) -> None:
        d = {"id": "x", "name": "X"}
        with pytest.raises((KeyError, ValueError)):
            criteria_from_dict(d)


# ---------------------------------------------------------------------------
# ProactiveCriteria — AND group
# ---------------------------------------------------------------------------


class TestCriteriaGroupAnd:
    _DICT = {
        "id": "projects_hesitation",
        "name": "Projects hesitation",
        "operator": "AND",
        "conditions": [
            {"id": "on_projects", "name": "On projects URL", "type": "url_contains"},
            {"id": "ping_pong", "name": "Ping-pong", "type": "canonical_url_ping_pong"},
        ],
    }

    def test_from_dict_produces_group(self) -> None:
        group = criteria_from_dict(self._DICT)
        assert isinstance(group, CriteriaGroup)
        assert group.operator == "AND"
        assert len(group.conditions) == 2

    def test_and_group_to_dict_round_trip(self) -> None:
        group = criteria_from_dict(self._DICT)
        assert group.to_dict() == self._DICT

    def test_group_children_are_leaves(self) -> None:
        group = criteria_from_dict(self._DICT)
        assert isinstance(group, CriteriaGroup)
        assert all(isinstance(c, CriteriaLeaf) for c in group.conditions)

    def test_group_missing_conditions_raises(self) -> None:
        d = {"id": "g1", "name": "G", "operator": "AND"}
        with pytest.raises((KeyError, ValueError)):
            criteria_from_dict(d)

    def test_group_empty_conditions_raises(self) -> None:
        d = {"id": "g1", "name": "G", "operator": "AND", "conditions": []}
        with pytest.raises(ValueError):
            criteria_from_dict(d)


# ---------------------------------------------------------------------------
# ProactiveCriteria — OR group
# ---------------------------------------------------------------------------


class TestCriteriaGroupOr:
    _DICT = {
        "id": "any_of",
        "name": "Any of",
        "operator": "OR",
        "conditions": [
            {"id": "c1", "name": "Cond 1", "type": "type_a"},
            {"id": "c2", "name": "Cond 2", "type": "type_b"},
        ],
    }

    def test_from_dict_produces_or_group(self) -> None:
        group = criteria_from_dict(self._DICT)
        assert isinstance(group, CriteriaGroup)
        assert group.operator == "OR"

    def test_or_group_round_trip(self) -> None:
        group = criteria_from_dict(self._DICT)
        assert group.to_dict() == self._DICT


# ---------------------------------------------------------------------------
# ProactiveCriteria — nested (AND containing an OR group)
# ---------------------------------------------------------------------------


class TestCriteriaNestedGroup:
    _DICT = {
        "id": "outer_and",
        "name": "Outer AND",
        "operator": "AND",
        "conditions": [
            {
                "id": "inner_or",
                "name": "Inner OR",
                "operator": "OR",
                "conditions": [
                    {"id": "leaf1", "name": "Leaf 1", "type": "type_x"},
                    {"id": "leaf2", "name": "Leaf 2", "type": "type_y"},
                ],
            },
            {"id": "leaf3", "name": "Leaf 3", "type": "type_z"},
        ],
    }

    def test_nested_from_dict_structure(self) -> None:
        outer = criteria_from_dict(self._DICT)
        assert isinstance(outer, CriteriaGroup)
        assert outer.operator == "AND"

        inner = outer.conditions[0]
        assert isinstance(inner, CriteriaGroup)
        assert inner.operator == "OR"
        assert len(inner.conditions) == 2
        assert all(isinstance(c, CriteriaLeaf) for c in inner.conditions)

        assert isinstance(outer.conditions[1], CriteriaLeaf)

    def test_nested_round_trip_preserves_depth(self) -> None:
        outer = criteria_from_dict(self._DICT)
        assert outer.to_dict() == self._DICT


# ---------------------------------------------------------------------------
# CriteriaGroup validation
# ---------------------------------------------------------------------------


class TestCriteriaGroupValidation:
    def test_invalid_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="operator must be 'AND' or 'OR'"):
            CriteriaGroup(
                id="g",
                name="G",
                operator="XOR",
                conditions=[CriteriaLeaf(id="l", name="L", type="t")],
            )

    def test_empty_conditions_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            CriteriaGroup(id="g", name="G", operator="AND", conditions=[])


# ---------------------------------------------------------------------------
# ProactiveTriggerConfig
# ---------------------------------------------------------------------------


_LEAF_DICT = {"id": "url_change", "name": "URL change", "type": "url_change"}
_MSG_1 = {"id": "chip_1", "label": "Label 1", "user_tour_exists": False}
_MSG_2 = {"id": "chip_2", "label": "Label 2", "user_tour_exists": False}
_MSG_3 = {"id": "chip_3", "label": "Label 3", "user_tour_exists": False}
_MSG_4 = {"id": "chip_4", "label": "Label 4", "user_tour_exists": False}


class TestProactiveTriggerConfig:
    def _make_config(self, messages: list[dict]) -> dict:
        return {
            "id": "trig_1",
            "name": "Test trigger",
            "proactive_criteria": _LEAF_DICT,
            "messages": messages,
        }

    def test_zero_messages_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1 message"):
            ProactiveTriggerConfig.from_dict(self._make_config([]))

    def test_four_messages_raises(self) -> None:
        with pytest.raises(ValueError, match="max 3 messages"):
            ProactiveTriggerConfig.from_dict(
                self._make_config([_MSG_1, _MSG_2, _MSG_3, _MSG_4])
            )

    def test_one_message_constructs_fine(self) -> None:
        cfg = ProactiveTriggerConfig.from_dict(self._make_config([_MSG_1]))
        assert len(cfg.messages) == 1

    def test_three_messages_constructs_fine(self) -> None:
        cfg = ProactiveTriggerConfig.from_dict(
            self._make_config([_MSG_1, _MSG_2, _MSG_3])
        )
        assert len(cfg.messages) == 3

    def test_from_dict_round_trip_simple_leaf(self) -> None:
        raw = self._make_config([_MSG_1, _MSG_2])
        cfg = ProactiveTriggerConfig.from_dict(raw)
        assert cfg.to_dict() == raw

    def test_from_dict_round_trip_compound_criteria(self) -> None:
        compound = {
            "id": "outer_and",
            "name": "Outer AND",
            "operator": "AND",
            "conditions": [
                {
                    "id": "inner_or",
                    "name": "Inner OR",
                    "operator": "OR",
                    "conditions": [
                        {"id": "l1", "name": "L1", "type": "type_a"},
                        {"id": "l2", "name": "L2", "type": "type_b"},
                    ],
                },
                {"id": "l3", "name": "L3", "type": "type_c"},
            ],
        }
        raw = {
            "id": "trig_compound",
            "name": "Compound trigger",
            "proactive_criteria": compound,
            "messages": [_MSG_1],
        }
        cfg = ProactiveTriggerConfig.from_dict(raw)
        assert cfg.to_dict() == raw

    def test_from_dict_with_tour_message(self) -> None:
        msg_with_tour = {
            "id": "chip_tour",
            "label": "Take the tour",
            "user_tour_exists": True,
            "user_tour_id": "flow_abc",
        }
        raw = self._make_config([msg_with_tour])
        cfg = ProactiveTriggerConfig.from_dict(raw)
        assert cfg.messages[0].user_tour_exists is True
        assert cfg.messages[0].user_tour_id == "flow_abc"
