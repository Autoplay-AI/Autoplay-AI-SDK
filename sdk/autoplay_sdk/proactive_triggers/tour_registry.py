"""Tour registry — per-product catalogue of visual guidance tours.

Stored at ``integration_config.tour_registry`` (a list), independent of
``proactive_intercom``.  When a proactive chip fires and needs to launch a
visual tour, the connector looks up the matching :class:`TourDefinition` by id.

Each ``TourDefinition`` carries its own ``interaction_timeout_s`` and
``cooldown_period_s`` overrides.  If an entry omits these, the registry-level
defaults are used instead.

Chip labels and tour-existence flags live on ``proactive_intercom.messages``
and are not duplicated here.

JSON shape::

    "tour_registry": [
      {
        "id": "chip_new_project",
        "user_tour_id": "cmolleaj6028o13fcrnne0tsy",
        "user_tour_name": "Create new project",
        "interaction_timeout_s": 30.0,
        "cooldown_period_s": 120.0
      }
    ]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_INTERACTION_TIMEOUT_S: float = 20.0
DEFAULT_COOLDOWN_PERIOD_S: float = 120.0


# ---------------------------------------------------------------------------
# TourDefinition
# ---------------------------------------------------------------------------


@dataclass
class TourDefinition:
    """One entry in the tour registry for a product.

    Fields
    ------
    id                    : str        – stable identifier; matches the chip ``id`` in
                                         ``proactive_intercom[*].messages[*].id``
    user_tour_id          : str | None – tour provider flow id used to launch the tour
    user_tour_name        : str | None – human-readable tour name for logs / dashboards
    interaction_timeout_s : float      – how long without interaction before returning to
                                         THINKING; overrides the registry-level default
    cooldown_period_s     : float      – how long THINKING waits before proactive can fire
                                         again; overrides the registry-level default

    Note: ``label`` and ``user_tour_exists`` are intentionally omitted — those fields
    live on ``proactive_intercom.messages`` and are not duplicated in the registry.
    """

    id: str
    user_tour_id: str | None = None
    user_tour_name: str | None = None
    interaction_timeout_s: float = DEFAULT_INTERACTION_TIMEOUT_S
    cooldown_period_s: float = DEFAULT_COOLDOWN_PERIOD_S

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "interaction_timeout_s": self.interaction_timeout_s,
            "cooldown_period_s": self.cooldown_period_s,
        }
        if self.user_tour_id is not None:
            d["user_tour_id"] = self.user_tour_id
        if self.user_tour_name is not None:
            d["user_tour_name"] = self.user_tour_name
        return d

    @classmethod
    def from_dict(
        cls, d: dict, *, registry_defaults: dict | None = None
    ) -> TourDefinition:
        """Parse one tour entry.

        ``registry_defaults`` may supply ``default_interaction_timeout_s`` and
        ``default_cooldown_period_s`` which are used as fallbacks when the entry
        itself does not specify timeout values.

        Legacy ``label`` and ``user_tour_exists`` keys are silently ignored if
        present so existing configs do not break on deploy.
        """
        defs = registry_defaults or {}
        return cls(
            id=d["id"],
            user_tour_id=d.get("user_tour_id"),
            user_tour_name=d.get("user_tour_name"),
            interaction_timeout_s=d.get(
                "interaction_timeout_s",
                defs.get(
                    "default_interaction_timeout_s", DEFAULT_INTERACTION_TIMEOUT_S
                ),
            ),
            cooldown_period_s=d.get(
                "cooldown_period_s",
                defs.get("default_cooldown_period_s", DEFAULT_COOLDOWN_PERIOD_S),
            ),
        )


# ---------------------------------------------------------------------------
# TourRegistry
# ---------------------------------------------------------------------------


@dataclass
class TourRegistry:
    """All tours for one product.

    Fields
    ------
    product_id                    : str
    tours                         : list[TourDefinition]
    default_interaction_timeout_s : float – fallback for entries that don't set their own
    default_cooldown_period_s     : float – fallback for entries that don't set their own
    """

    product_id: str
    tours: list[TourDefinition] = field(default_factory=list)
    default_interaction_timeout_s: float = DEFAULT_INTERACTION_TIMEOUT_S
    default_cooldown_period_s: float = DEFAULT_COOLDOWN_PERIOD_S

    def get(self, tour_id: str) -> TourDefinition | None:
        """Look up a tour by chip ``id``. Returns ``None`` if not found."""
        for tour in self.tours:
            if tour.id == tour_id:
                return tour
        return None

    def get_by_user_tour_id(self, user_tour_id: str) -> TourDefinition | None:
        """Look up a tour by its ``user_tour_id`` (tour provider flow ID).

        Use this when ``active_tour_id`` on :class:`SessionState` holds the
        tour provider flow ID (e.g. ``"cmolleaj6028o13fcrnne0tsy"``).
        Returns ``None`` if not found or if ``user_tour_id`` is falsy.
        """
        if not user_tour_id:
            return None
        for tour in self.tours:
            if tour.user_tour_id == user_tour_id:
                return tour
        return None

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "default_interaction_timeout_s": self.default_interaction_timeout_s,
            "default_cooldown_period_s": self.default_cooldown_period_s,
            "tours": [t.to_dict() for t in self.tours],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TourRegistry:
        registry_defaults = {
            "default_interaction_timeout_s": d.get(
                "default_interaction_timeout_s", DEFAULT_INTERACTION_TIMEOUT_S
            ),
            "default_cooldown_period_s": d.get(
                "default_cooldown_period_s", DEFAULT_COOLDOWN_PERIOD_S
            ),
        }
        tours: list[TourDefinition] = []
        for i, entry in enumerate(d.get("tours", [])):
            if not isinstance(entry, dict):
                logger.warning(
                    "tour_registry: tours[%d] expected dict, got %s — skipping",
                    i,
                    type(entry).__name__,
                    extra={
                        "event_type": "tour_registry_entry_invalid_type",
                        "index": i,
                        "got_type": type(entry).__name__,
                    },
                )
                continue
            try:
                tours.append(
                    TourDefinition.from_dict(entry, registry_defaults=registry_defaults)
                )
            except Exception as exc:
                logger.warning(
                    "tour_registry: tours[%d] failed to parse — skipping: %s",
                    i,
                    exc,
                    exc_info=True,
                    extra={
                        "event_type": "tour_registry_entry_parse_error",
                        "index": i,
                    },
                )
        return cls(
            product_id=d["product_id"],
            default_interaction_timeout_s=registry_defaults[
                "default_interaction_timeout_s"
            ],
            default_cooldown_period_s=registry_defaults["default_cooldown_period_s"],
            tours=tours,
        )
