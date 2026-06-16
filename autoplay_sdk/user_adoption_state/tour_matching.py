"""Reusable query -> tour matching primitive.

Generalises the LeytonGo ``[TOUR:<id>]`` / ``[RELATED_TOURS:...]`` system-prompt
logic (role filter + primary/related tour selection) into SDK helpers that any
integration can reuse. This module is pure: it builds the structured prompt
input and parses/validates the LLM output. The actual ``acall_llm`` invocation
lives in the connector.

Catalog shape (a list of dicts, decoupled from any one config format)::

    [
      {"tour_id": "flow-consultant-projects",
       "name": "Browse projects",
       "use_when": "user wants to find / filter / browse existing projects",
       "role": "consultant"},
      ...
    ]

``role`` is optional per entry; ``None`` / missing means all roles.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TourCatalogEntry:
    tour_id: str
    name: str = ""
    use_when: str = ""
    role: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> TourCatalogEntry:
        return cls(
            tour_id=str(d.get("tour_id") or d.get("user_tour_id") or d.get("id") or ""),
            name=str(d.get("name") or d.get("user_tour_name") or ""),
            use_when=str(d.get("use_when") or d.get("description") or ""),
            role=(str(d["role"]) if d.get("role") is not None else None),
        )


@dataclass
class TourMatchResult:
    primary_tour_id: str | None = None
    related_tour_ids: list[str] = field(default_factory=list)
    reasoning: str = ""


def _normalize_catalog(
    tour_catalog: list[dict] | list[TourCatalogEntry],
) -> list[TourCatalogEntry]:
    out: list[TourCatalogEntry] = []
    for entry in tour_catalog:
        if isinstance(entry, TourCatalogEntry):
            if entry.tour_id:
                out.append(entry)
        elif isinstance(entry, dict):
            parsed = TourCatalogEntry.from_dict(entry)
            if parsed.tour_id:
                out.append(parsed)
    return out


def _role_allows(entry: TourCatalogEntry, role: str | None) -> bool:
    if entry.role is None:
        return True
    return entry.role.strip().lower() == (role or "").strip().lower()


def build_tour_match_input(
    *,
    user_query: str,
    conversation_history: str = "",
    role: str | None = None,
    current_page: str | None = None,
    tour_catalog: list[dict] | list[TourCatalogEntry],
) -> dict:
    """Assemble the structured input for the tour-match prompt.

    The catalog is pre-filtered to the user's role so the model can only pick
    role-appropriate tours.
    """
    entries = [e for e in _normalize_catalog(tour_catalog) if _role_allows(e, role)]
    catalog_lines = [
        f"{e.tour_id} :: {e.name} :: {e.use_when}".rstrip(": ") for e in entries
    ]
    return {
        "user_query": user_query,
        "conversation_history": conversation_history or "(none)",
        "role": role or "unknown",
        "current_page": current_page or "unknown",
        "tour_catalog_text": "\n".join(catalog_lines) or "(no tours available)",
        "allowed_tour_ids": [e.tour_id for e in entries],
    }


def parse_tour_match_output(
    raw: str,
    *,
    tour_catalog: list[dict] | list[TourCatalogEntry],
    role: str | None = None,
) -> TourMatchResult:
    """Parse the LLM JSON output, validating ids against the role-filtered catalog.

    Safe fallback to an empty result (``primary_tour_id=None``) on parse error,
    so a malformed model response never raises into the caller.
    """
    allowed = {
        e.tour_id for e in _normalize_catalog(tour_catalog) if _role_allows(e, role)
    }
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "tour_matching: failed to parse output — returning empty match: %s",
            exc,
            extra={"event_type": "tour_match_parse_error"},
        )
        return TourMatchResult(reasoning="parse_error")

    if not isinstance(data, dict):
        return TourMatchResult(reasoning="parse_error")

    primary = data.get("primary_tour_id")
    primary_id = str(primary) if primary else None
    if primary_id is not None and primary_id not in allowed:
        primary_id = None

    related: list[str] = []
    for rid in data.get("related_tour_ids") or []:
        rid_s = str(rid)
        if rid_s in allowed and rid_s != primary_id and rid_s not in related:
            related.append(rid_s)

    return TourMatchResult(
        primary_tour_id=primary_id,
        related_tour_ids=related,
        reasoning=str(data.get("reasoning", "")),
    )
