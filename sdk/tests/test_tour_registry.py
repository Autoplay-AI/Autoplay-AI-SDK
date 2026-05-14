"""Tests for TourDefinition, TourRegistry, and parse_tour_registry."""

from __future__ import annotations


from autoplay_sdk.proactive_triggers.tour_registry import (
    DEFAULT_COOLDOWN_PERIOD_S,
    DEFAULT_INTERACTION_TIMEOUT_S,
    TourDefinition,
    TourRegistry,
)
from autoplay_sdk.proactive_triggers.proactive_intercom_config import (
    parse_tour_registry,
)

# ---------------------------------------------------------------------------
# TourDefinition
# ---------------------------------------------------------------------------


class TestTourDefinition:
    def _minimal_dict(self) -> dict:
        return {"id": "tour_1"}

    def _full_dict(self) -> dict:
        return {
            "id": "tour_1",
            "user_tour_id": "flow_abc",
            "user_tour_name": "Billing Tour",
            "interaction_timeout_s": 30.0,
            "cooldown_period_s": 90.0,
        }

    # --- defaults ---------------------------------------------------------

    def test_from_dict_uses_module_defaults_when_timeouts_absent(self) -> None:
        td = TourDefinition.from_dict(self._minimal_dict())
        assert td.interaction_timeout_s == DEFAULT_INTERACTION_TIMEOUT_S
        assert td.cooldown_period_s == DEFAULT_COOLDOWN_PERIOD_S

    def test_from_dict_uses_registry_defaults_when_entry_omits_timeouts(self) -> None:
        registry_defaults = {
            "default_interaction_timeout_s": 45.0,
            "default_cooldown_period_s": 200.0,
        }
        td = TourDefinition.from_dict(
            self._minimal_dict(), registry_defaults=registry_defaults
        )
        assert td.interaction_timeout_s == 45.0
        assert td.cooldown_period_s == 200.0

    def test_from_dict_uses_own_values_when_both_set(self) -> None:
        td = TourDefinition.from_dict(
            self._full_dict(),
            registry_defaults={
                "default_interaction_timeout_s": 999.0,
                "default_cooldown_period_s": 999.0,
            },
        )
        assert td.interaction_timeout_s == 30.0
        assert td.cooldown_period_s == 90.0

    # --- round-trip -------------------------------------------------------

    def test_to_dict_from_dict_round_trip(self) -> None:
        td = TourDefinition.from_dict(self._full_dict())
        restored = TourDefinition.from_dict(td.to_dict())
        assert restored.id == td.id
        assert restored.user_tour_id == td.user_tour_id
        assert restored.user_tour_name == td.user_tour_name
        assert restored.interaction_timeout_s == td.interaction_timeout_s
        assert restored.cooldown_period_s == td.cooldown_period_s

    def test_to_dict_omits_none_optional_fields(self) -> None:
        td = TourDefinition(id="t1")
        d = td.to_dict()
        assert "user_tour_id" not in d
        assert "user_tour_name" not in d

    def test_legacy_label_and_user_tour_exists_are_silently_ignored(self) -> None:
        """Configs with old fields should still parse without error."""
        d = {
            "id": "tour_1",
            "label": "Legacy label",
            "user_tour_exists": True,
            "user_tour_id": "flow_abc",
        }
        td = TourDefinition.from_dict(d)
        assert td.id == "tour_1"
        assert td.user_tour_id == "flow_abc"
        assert not hasattr(td, "label")
        assert not hasattr(td, "user_tour_exists")


# ---------------------------------------------------------------------------
# TourRegistry
# ---------------------------------------------------------------------------


class TestTourRegistry:
    def _registry_dict(self) -> dict:
        return {
            "product_id": "prod_abc",
            "default_interaction_timeout_s": 25.0,
            "default_cooldown_period_s": 150.0,
            "tours": [
                {
                    "id": "tour_billing",
                    "user_tour_id": "flow_billing",
                    "user_tour_name": "Billing Tour",
                    "interaction_timeout_s": 30.0,
                    "cooldown_period_s": 90.0,
                },
                {
                    "id": "tour_onboarding",
                },
            ],
        }

    def test_get_returns_correct_tour(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        tour = registry.get("tour_billing")
        assert tour is not None
        assert tour.id == "tour_billing"
        assert tour.user_tour_id == "flow_billing"

    def test_get_unknown_returns_none(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        assert registry.get("does_not_exist") is None

    def test_get_by_user_tour_id_returns_correct_tour(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        tour = registry.get_by_user_tour_id("flow_billing")
        assert tour is not None
        assert tour.id == "tour_billing"
        assert tour.user_tour_id == "flow_billing"

    def test_get_by_user_tour_id_unknown_returns_none(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        assert registry.get_by_user_tour_id("nonexistent_flow") is None

    def test_get_by_user_tour_id_empty_string_returns_none(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        assert registry.get_by_user_tour_id("") is None

    def test_get_by_user_tour_id_does_not_match_chip_id(self) -> None:
        """Confirm get_by_user_tour_id does NOT match on chip id."""
        registry = TourRegistry.from_dict(self._registry_dict())
        assert registry.get_by_user_tour_id("tour_billing") is None

    def test_entry_without_timeouts_inherits_registry_defaults(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        onboarding = registry.get("tour_onboarding")
        assert onboarding is not None
        assert onboarding.interaction_timeout_s == 25.0
        assert onboarding.cooldown_period_s == 150.0

    def test_full_round_trip(self) -> None:
        registry = TourRegistry.from_dict(self._registry_dict())
        d = registry.to_dict()
        restored = TourRegistry.from_dict(d)
        assert restored.product_id == registry.product_id
        assert (
            restored.default_interaction_timeout_s
            == registry.default_interaction_timeout_s
        )
        assert restored.default_cooldown_period_s == registry.default_cooldown_period_s
        assert len(restored.tours) == len(registry.tours)
        assert restored.tours[0].id == registry.tours[0].id

    def test_malformed_entry_is_skipped_not_raised(self) -> None:
        d = {
            "product_id": "prod_x",
            "tours": [
                "not_a_dict",
                {"id": "ok_tour"},
            ],
        }
        registry = TourRegistry.from_dict(d)
        assert len(registry.tours) == 1
        assert registry.tours[0].id == "ok_tour"


# ---------------------------------------------------------------------------
# parse_tour_registry
# ---------------------------------------------------------------------------


class TestParseTourRegistry:
    def test_returns_none_when_key_absent(self) -> None:
        result = parse_tour_registry({"other_key": "value"}, product_id="p1")
        assert result is None

    def test_returns_none_when_not_a_list(self) -> None:
        result = parse_tour_registry({"tour_registry": {"id": "oops"}}, product_id="p1")
        assert result is None

    def test_returns_none_when_integration_config_is_none(self) -> None:
        result = parse_tour_registry(None, product_id="p1")
        assert result is None

    def test_returns_registry_when_key_present(self) -> None:
        integration_config = {
            "tour_registry": [
                {
                    "id": "chip_new_project",
                    "user_tour_id": "cmolleaj6028o13fcrnne0tsy",
                    "user_tour_name": "Create new project",
                    "interaction_timeout_s": 30.0,
                    "cooldown_period_s": 120.0,
                }
            ]
        }
        registry = parse_tour_registry(integration_config, product_id="499c2d1b")
        assert registry is not None
        assert registry.product_id == "499c2d1b"
        assert len(registry.tours) == 1
        tour = registry.get("chip_new_project")
        assert tour is not None
        assert tour.user_tour_id == "cmolleaj6028o13fcrnne0tsy"
        assert tour.interaction_timeout_s == 30.0
        assert tour.cooldown_period_s == 120.0

    def test_empty_list_returns_empty_registry(self) -> None:
        registry = parse_tour_registry({"tour_registry": []}, product_id="p1")
        assert registry is not None
        assert registry.tours == []
