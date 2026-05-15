"""Tests for built-in proactive trigger catalog and registry_from_builtin_specs."""

from __future__ import annotations

import pytest

from autoplay_sdk.exceptions import SdkConfigError
from autoplay_sdk.proactive_triggers.builtin_catalog import (
    BUILTIN_TRIGGER_CATALOG,
    list_builtin_trigger_catalog,
    registry_from_builtin_specs,
    resolve_builtin_specs,
)
from autoplay_sdk.proactive_triggers.defaults import TRIGGER_ID_CANONICAL_URL_PING_PONG
from autoplay_sdk.proactive_triggers.judge import TRIGGERING_TYPE_LLM_JUDGE
from autoplay_sdk.proactive_triggers.types import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_INTERACTION_TIMEOUT_S,
)

_PING = BUILTIN_TRIGGER_CATALOG[TRIGGER_ID_CANONICAL_URL_PING_PONG]


def _ping_row(**extra: object) -> dict:
    return {
        "id": TRIGGER_ID_CANONICAL_URL_PING_PONG,
        "name": _PING.name,
        "description": _PING.description,
        **extra,
    }


def test_catalog_contains_ping_pong() -> None:
    assert TRIGGER_ID_CANONICAL_URL_PING_PONG in BUILTIN_TRIGGER_CATALOG


def test_list_builtin_trigger_catalog_shape() -> None:
    rows = list_builtin_trigger_catalog()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    ping = next(r for r in rows if r["id"] == TRIGGER_ID_CANONICAL_URL_PING_PONG)
    assert ping["name"]
    assert ping["description"]
    assert ping["interaction_timeout_s"] == DEFAULT_INTERACTION_TIMEOUT_S
    assert ping["cooldown_s"] == DEFAULT_COOLDOWN_S
    assert ping["default_triggering_type"] == TRIGGERING_TYPE_LLM_JUDGE


def test_resolve_builtin_specs_with_overrides() -> None:
    resolved = resolve_builtin_specs(
        [
            {
                **_ping_row(),
                "interaction_timeout_s": 99,
                "cooldown_s": 45,
            }
        ]
    )
    assert len(resolved) == 1
    assert resolved[0].name == _PING.name
    assert resolved[0].description == _PING.description
    assert resolved[0].interaction_timeout_s == 99.0
    assert resolved[0].cooldown_s == 45.0
    assert resolved[0].triggering_type == TRIGGERING_TYPE_LLM_JUDGE


def test_resolve_requires_nonempty_name_and_description() -> None:
    with pytest.raises(SdkConfigError, match="field 'name' must be a string"):
        resolve_builtin_specs(
            [{"id": TRIGGER_ID_CANONICAL_URL_PING_PONG, "description": "d"}]
        )
    with pytest.raises(SdkConfigError, match="field 'description' must be a string"):
        resolve_builtin_specs(
            [
                {
                    "id": TRIGGER_ID_CANONICAL_URL_PING_PONG,
                    "name": _PING.name,
                }
            ]
        )
    with pytest.raises(SdkConfigError, match="non-empty string 'description'"):
        resolve_builtin_specs(
            [
                {
                    "id": TRIGGER_ID_CANONICAL_URL_PING_PONG,
                    "name": _PING.name,
                    "description": "   ",
                }
            ]
        )
    with pytest.raises(SdkConfigError, match="field 'name' must be a string"):
        resolve_builtin_specs(
            [
                {
                    "id": TRIGGER_ID_CANONICAL_URL_PING_PONG,
                    "name": 123,
                    "description": _PING.description,
                }
            ]
        )


def test_unknown_builtin_id_raises() -> None:
    with pytest.raises(SdkConfigError, match="unknown proactive builtin"):
        registry_from_builtin_specs(
            [
                {
                    "id": "not_a_real_builtin",
                    "name": "x",
                    "description": "y",
                }
            ]
        )


def test_registry_matches_default_singleton_equivalence() -> None:
    from autoplay_sdk.proactive_triggers import default_proactive_trigger_registry

    a = default_proactive_trigger_registry()
    b = registry_from_builtin_specs([_ping_row()])
    assert len(a.triggers) == len(b.triggers) == 1
    assert type(a.triggers[0]).__name__ == type(b.triggers[0]).__name__


def test_empty_specs_raises() -> None:
    with pytest.raises(SdkConfigError, match="non-empty"):
        registry_from_builtin_specs([])


def test_registry_preserves_spec_order() -> None:
    """Duplicate catalog ids still produce separate slots in list order (first match wins)."""
    reg = registry_from_builtin_specs(
        [
            {**_ping_row(), "cooldown_s": 40},
            {**_ping_row(), "cooldown_s": 50},
        ]
    )
    assert len(reg.triggers) == 2
    assert reg.triggers[0].trigger_id == TRIGGER_ID_CANONICAL_URL_PING_PONG
    assert reg.triggers[1].trigger_id == TRIGGER_ID_CANONICAL_URL_PING_PONG
    assert reg.triggers[1].timings.cooldown_s == 50.0
