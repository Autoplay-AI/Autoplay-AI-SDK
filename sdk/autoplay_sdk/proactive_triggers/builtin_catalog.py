"""Built-in proactive triggers — catalog metadata, JSON specs, and registry building.

Only **SDK catalog** triggers are configurable from connector JSON
(:func:`registry_from_builtin_specs`). The catalog grows over time (today:
``canonical_url_ping_pong``). Custom :class:`~autoplay_sdk.proactive_triggers.types.ProactiveTrigger`
implementations live **outside** this module — compose :class:`ProactiveTriggerRegistry`
in application code; the connector does not load arbitrary triggers from config.

Invalid rows (bad types, unknown ``id``, empty ``builtins`` when non-empty list is required,
etc.) raise :exc:`~autoplay_sdk.exceptions.SdkConfigError` and are logged at **ERROR** with
``extra["event"] == "proactive_builtin_spec_invalid"`` for operator visibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from autoplay_sdk.exceptions import SdkConfigError
from autoplay_sdk.proactive_triggers.defaults import (
    TRIGGER_ID_CANONICAL_URL_PING_PONG,
    TRIGGER_ID_SECTION_PLAYBOOK_MATCH,
    TRIGGER_ID_USER_PAGE_DWELL,
)
from autoplay_sdk.proactive_triggers.entity import ProactiveTriggerEntity
from autoplay_sdk.proactive_triggers.judge import TRIGGERING_TYPE_LLM_JUDGE
from autoplay_sdk.proactive_triggers.registry import ProactiveTriggerRegistry
from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_INTERACTION_TIMEOUT_S,
    ProactiveTrigger,
    ProactiveTriggerTimings,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedBuiltinTriggerSpec:
    """Effective built-in trigger row after merging catalog defaults with JSON overrides."""

    id: str
    name: str
    description: str
    interaction_timeout_s: float
    cooldown_s: float
    triggering_type: str


@dataclass(frozen=True)
class BuiltinTriggerCatalogEntry:
    """One SDK built-in: stable id, display metadata, default timings, factory for inner trigger.

    **id**, **name**, and **description** are required strings for every catalog entry; host
    config rows must also supply all three (see :func:`resolve_builtin_specs`).
    """

    id: str
    name: str
    description: str
    default_interaction_timeout_s: float
    default_cooldown_s: float
    default_triggering_type: str
    inner_factory: Callable[[], ProactiveTrigger]

    def build(
        self,
        timings: ProactiveTriggerTimings | None,
        *,
        triggering_type: str | None = None,
    ) -> ProactiveTrigger:
        """Return a trigger wired for :class:`ProactiveTriggerRegistry` (wrapped with timings)."""
        t = (
            timings
            if timings is not None
            else ProactiveTriggerTimings(
                interaction_timeout_s=self.default_interaction_timeout_s,
                cooldown_s=self.default_cooldown_s,
            )
        )
        tt = (
            triggering_type
            if triggering_type is not None
            else self.default_triggering_type
        )
        return ProactiveTriggerEntity(self.inner_factory(), t, triggering_type=tt)


def _catalog_dict() -> dict[str, BuiltinTriggerCatalogEntry]:
    from autoplay_sdk.proactive_triggers.triggers.canonical_ping_pong import (
        CanonicalPingPongTrigger,
    )
    from autoplay_sdk.proactive_triggers.triggers.user_page_dwell import (
        UserPageDwellTrigger,
    )
    from autoplay_sdk.proactive_triggers.triggers.section_playbook import (
        SectionPlaybookTrigger,
    )

    ping_pong = BuiltinTriggerCatalogEntry(
        id=TRIGGER_ID_CANONICAL_URL_PING_PONG,
        name="URL ping-pong (hesitation)",
        description=(
            "User hesitates with repeated back-and-forth navigation across canonical URLs "
            "(ping-pong pattern) before asking for help."
        ),
        default_interaction_timeout_s=DEFAULT_INTERACTION_TIMEOUT_S,
        default_cooldown_s=DEFAULT_COOLDOWN_S,
        default_triggering_type=TRIGGERING_TYPE_LLM_JUDGE,
        inner_factory=lambda: CanonicalPingPongTrigger(),
    )
    user_page_dwell = BuiltinTriggerCatalogEntry(
        id=TRIGGER_ID_USER_PAGE_DWELL,
        name="User page dwell (sparse linger)",
        description=(
            "User stays on the same canonical URL for at least dwell_threshold_seconds "
            "(default 60s) with at most user_page_dwell_max_actions actions on that streak "
            "(sparse activity; default 5)."
        ),
        default_interaction_timeout_s=DEFAULT_INTERACTION_TIMEOUT_S,
        default_cooldown_s=DEFAULT_COOLDOWN_S,
        default_triggering_type=TRIGGERING_TYPE_LLM_JUDGE,
        inner_factory=lambda: UserPageDwellTrigger(),
    )
    section = BuiltinTriggerCatalogEntry(
        id=TRIGGER_ID_SECTION_PLAYBOOK_MATCH,
        name="Section playbook match",
        description=(
            "Deterministic nudge from section_playbook using product_section_playbook "
            "metrics (URL rules) and optional current_section_id override."
        ),
        default_interaction_timeout_s=DEFAULT_INTERACTION_TIMEOUT_S,
        default_cooldown_s=DEFAULT_COOLDOWN_S,
        default_triggering_type=TRIGGERING_TYPE_LLM_JUDGE,
        inner_factory=lambda: SectionPlaybookTrigger(),
    )
    return {
        ping_pong.id: ping_pong,
        user_page_dwell.id: user_page_dwell,
        section.id: section,
    }


BUILTIN_TRIGGER_CATALOG: dict[str, BuiltinTriggerCatalogEntry] = _catalog_dict()


def _spec_config_error(
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    """Log at ERROR (structured) then raise :exc:`SdkConfigError` with ``message``."""
    logger.error(
        "%s",
        message,
        extra={"event": "proactive_builtin_spec_invalid"},
    )
    if cause is not None:
        raise SdkConfigError(message) from cause
    raise SdkConfigError(message)


def list_builtin_trigger_catalog() -> list[dict[str, Any]]:
    """Return catalog defaults for docs and UIs: ``id``, ``name``, ``description``, timings."""
    rows: list[dict[str, Any]] = []
    for e in sorted(BUILTIN_TRIGGER_CATALOG.values(), key=lambda x: x.id):
        rows.append(
            {
                "id": e.id,
                "name": e.name,
                "description": e.description,
                "interaction_timeout_s": e.default_interaction_timeout_s,
                "cooldown_s": e.default_cooldown_s,
                "default_triggering_type": e.default_triggering_type,
            }
        )
    return rows


def _require_nonempty_str(value: Any, field: str, row_index: int) -> str:
    """Return stripped string or raise :exc:`SdkConfigError` — **field** must be a non-empty ``str``."""
    if not isinstance(value, str):
        _spec_config_error(
            f"builtin trigger spec row {row_index} field {field!r} must be a string, "
            f"got {type(value).__name__}"
        )
    s = value.strip()
    if not s:
        _spec_config_error(
            f"builtin trigger spec row {row_index} must include non-empty string {field!r}"
        )
    return s


def _positive_float(name: str, value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        _spec_config_error(
            f"builtin trigger spec field {name!r} must be a positive number, got {value!r}",
            cause=exc,
        )
    if f <= 0:
        _spec_config_error(
            f"builtin trigger spec field {name!r} must be > 0, got {value!r}"
        )
    return f


def _parse_triggering_type(
    raw: Mapping[str, Any],
    entry: BuiltinTriggerCatalogEntry,
    row_index: int,
) -> str:
    from autoplay_sdk.proactive_triggers.judge import (
        TRIGGERING_TYPE_INSTANT,
        TRIGGERING_TYPE_LLM_JUDGE,
    )

    v = raw.get("triggering_type")
    if v is None:
        return entry.default_triggering_type
    if not isinstance(v, str):
        _spec_config_error(
            f"builtin trigger spec row {row_index} field 'triggering_type' must be a string"
        )
    s = v.strip()
    if s not in (TRIGGERING_TYPE_INSTANT, TRIGGERING_TYPE_LLM_JUDGE):
        _spec_config_error(
            f"builtin trigger spec row {row_index} triggering_type must be "
            f"{TRIGGERING_TYPE_INSTANT!r} or {TRIGGERING_TYPE_LLM_JUDGE!r}, got {s!r}"
        )
    return s


def _merge_timings(
    entry: BuiltinTriggerCatalogEntry, spec: Mapping[str, Any]
) -> ProactiveTriggerTimings:
    i_raw = spec.get("interaction_timeout_s")
    c_raw = spec.get("cooldown_s")
    interaction = (
        _positive_float("interaction_timeout_s", i_raw)
        if i_raw is not None
        else entry.default_interaction_timeout_s
    )
    cooldown = (
        _positive_float("cooldown_s", c_raw)
        if c_raw is not None
        else entry.default_cooldown_s
    )
    return ProactiveTriggerTimings(
        interaction_timeout_s=interaction,
        cooldown_s=cooldown,
    )


def resolve_builtin_specs(
    specs: Sequence[Mapping[str, Any]],
) -> list[ResolvedBuiltinTriggerSpec]:
    """Resolve each JSON row to effective ids, display fields, and timings (defaults + overrides).

    Each row **must** include **id**, **name**, and **description** as non-empty strings.
    **id** must match a :data:`BUILTIN_TRIGGER_CATALOG` key; **name** and **description** are
    host-supplied metadata (often aligned with :func:`list_builtin_trigger_catalog` defaults).

    On validation failure, logs **ERROR** with ``event=proactive_builtin_spec_invalid`` then
    raises :exc:`~autoplay_sdk.exceptions.SdkConfigError`.
    """
    out: list[ResolvedBuiltinTriggerSpec] = []
    for i, raw in enumerate(specs):
        tid = _require_nonempty_str(raw.get("id"), "id", i)
        name = _require_nonempty_str(raw.get("name"), "name", i)
        description = _require_nonempty_str(raw.get("description"), "description", i)
        entry = BUILTIN_TRIGGER_CATALOG.get(tid)
        if entry is None:
            _spec_config_error(
                f"unknown proactive builtin trigger id {tid!r}; "
                f"known ids: {sorted(BUILTIN_TRIGGER_CATALOG.keys())}"
            )
        timings = _merge_timings(entry, raw)
        tt = _parse_triggering_type(raw, entry, i)
        out.append(
            ResolvedBuiltinTriggerSpec(
                id=entry.id,
                name=name,
                description=description,
                interaction_timeout_s=timings.interaction_timeout_s,
                cooldown_s=timings.cooldown_s,
                triggering_type=tt,
            )
        )
    return out


def registry_from_builtin_specs(
    specs: Sequence[Mapping[str, Any]],
) -> ProactiveTriggerRegistry:
    """Build a :class:`ProactiveTriggerRegistry` from connector JSON rows (ordered; first match wins).

    Invalid specs log **ERROR** (``event=proactive_builtin_spec_invalid``) then raise.
    """
    if not specs:
        _spec_config_error(
            "builtins list must be non-empty — omit 'builtins' to use the legacy default registry"
        )
    resolved = resolve_builtin_specs(specs)
    triggers: list[ProactiveTrigger] = []
    for r in resolved:
        entry = BUILTIN_TRIGGER_CATALOG[r.id]
        timings = ProactiveTriggerTimings(
            interaction_timeout_s=r.interaction_timeout_s,
            cooldown_s=r.cooldown_s,
        )
        triggers.append(entry.build(timings, triggering_type=r.triggering_type))
    return ProactiveTriggerRegistry(triggers)
