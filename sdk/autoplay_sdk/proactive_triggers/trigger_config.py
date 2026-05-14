"""Proactive trigger configuration — TriggerMessage, recursive ProactiveCriteria, ProactiveTriggerConfig.

ProactiveCriteria is a recursive discriminated union::

    CriteriaLeaf   { id, name, type }
    CriteriaGroup  { id, name, operator: "AND"|"OR", conditions: list[...] }

Discriminated by the presence of ``"operator"`` in the serialised dict.
``criteria_from_dict()`` handles arbitrary nesting depth.

Example — simple leaf::

    {
      "id": "url_change",
      "name": "URL change",
      "type": "url_change"
    }

Example — compound AND group::

    {
      "id": "projects_hesitation",
      "name": "Projects hesitation",
      "operator": "AND",
      "conditions": [
        { "id": "on_projects", "name": "On projects URL", "type": "url_contains" },
        { "id": "ping_pong",   "name": "Ping-pong",       "type": "canonical_url_ping_pong" }
      ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


# ---------------------------------------------------------------------------
# TriggerMessage
# ---------------------------------------------------------------------------


@dataclass
class TriggerMessage:
    """One chip/option shown to the user when a proactive trigger fires.

    Fields
    ------
    id               : str       – stable identifier (e.g. ``"chip_new_project"``)
    label            : str       – display text shown in the chat chip
    user_tour_exists : bool      – whether this chip can launch a visual guidance tour
    user_tour_id     : str|None  – tour flow id; required when ``user_tour_exists`` is True
    """

    id: str
    label: str
    user_tour_exists: bool = False
    user_tour_id: str | None = None

    def __post_init__(self) -> None:
        if self.user_tour_exists and not self.user_tour_id:
            raise ValueError(
                f"TriggerMessage '{self.id}': user_tour_id is required when "
                "user_tour_exists is True"
            )

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "label": self.label,
            "user_tour_exists": self.user_tour_exists,
        }
        if self.user_tour_id is not None:
            d["user_tour_id"] = self.user_tour_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TriggerMessage:
        return cls(
            id=d["id"],
            label=d["label"],
            user_tour_exists=d.get("user_tour_exists", False),
            user_tour_id=d.get("user_tour_id"),
        )


# ---------------------------------------------------------------------------
# ProactiveCriteria — recursive tree
# ---------------------------------------------------------------------------


@dataclass
class CriteriaLeaf:
    """A single detection condition.

    Fields
    ------
    id   : str – stable machine identifier
    name : str – human-readable label
    type : str – detector key (e.g. ``"url_change"``, ``"canonical_url_ping_pong"``)
    """

    id: str
    name: str
    type: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type}


@dataclass
class CriteriaGroup:
    """A logical combinator of child criteria nodes.

    Fields
    ------
    id         : str                              – stable machine identifier
    name       : str                              – human-readable label
    operator   : str                              – ``"AND"`` or ``"OR"``
    conditions : list[CriteriaLeaf|CriteriaGroup] – child nodes (at least 1)
    """

    id: str
    name: str
    operator: str
    conditions: list[ProactiveCriteria] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.operator not in ("AND", "OR"):
            raise ValueError(
                f"CriteriaGroup '{self.id}': operator must be 'AND' or 'OR', "
                f"got {self.operator!r}"
            )
        if not self.conditions:
            raise ValueError(
                f"CriteriaGroup '{self.id}': conditions must be a non-empty list"
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "operator": self.operator,
            "conditions": [c.to_dict() for c in self.conditions],
        }


# Type alias — a criteria node is either a leaf or a group.
ProactiveCriteria = Union[CriteriaLeaf, CriteriaGroup]


def criteria_from_dict(d: dict) -> ProactiveCriteria:
    """Parse a criteria node dict, recursing into ``conditions`` for groups.

    Discriminates on the presence of ``"operator"``:
    - present  → :class:`CriteriaGroup` (recurses into each condition)
    - absent   → :class:`CriteriaLeaf`  (requires ``"type"``)
    """
    if "operator" in d:
        raw_conditions = d.get("conditions")
        if not isinstance(raw_conditions, list) or not raw_conditions:
            raise ValueError(
                f"CriteriaGroup '{d.get('id')}': 'conditions' must be a non-empty list"
            )
        return CriteriaGroup(
            id=d["id"],
            name=d["name"],
            operator=d["operator"],
            conditions=[criteria_from_dict(c) for c in raw_conditions],
        )
    if "type" not in d:
        raise ValueError(
            f"CriteriaLeaf '{d.get('id')}': 'type' field is required for leaf nodes"
        )
    return CriteriaLeaf(id=d["id"], name=d["name"], type=d["type"])


# ---------------------------------------------------------------------------
# ProactiveTriggerConfig
# ---------------------------------------------------------------------------

_MAX_MESSAGES = 3


@dataclass
class ProactiveTriggerConfig:
    """Configuration for one proactive trigger.

    Fields
    ------
    id                 : str               – stable machine identifier, never changes
    name               : str               – human-readable label for dashboards/logs
    proactive_criteria : ProactiveCriteria – detection rule (leaf or recursive group)
    messages           : list[TriggerMessage] – 1 to 3 chips shown when trigger fires
    """

    id: str
    name: str
    proactive_criteria: ProactiveCriteria
    messages: list[TriggerMessage]

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError(
                f"ProactiveTriggerConfig '{self.id}': must have at least 1 message"
            )
        if len(self.messages) > _MAX_MESSAGES:
            raise ValueError(
                f"ProactiveTriggerConfig '{self.id}': max {_MAX_MESSAGES} messages, "
                f"got {len(self.messages)}"
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "proactive_criteria": self.proactive_criteria.to_dict(),
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProactiveTriggerConfig:
        return cls(
            id=d["id"],
            name=d["name"],
            proactive_criteria=criteria_from_dict(d["proactive_criteria"]),
            messages=[TriggerMessage.from_dict(m) for m in d["messages"]],
        )
