"""Per-user adoption state: journey + mastery + onboarding lifecycle.

Orthogonal to the per-session ``AgentStateV2`` FSM. Keyed by ``user_id`` and
persisted by the connector. See :mod:`autoplay_sdk.user_adoption_state.models`.
"""

from autoplay_sdk.user_adoption_state.exploration_gate import (
    ExplorationGateConfig,
    evaluate_hard_gate,
)
from autoplay_sdk.user_adoption_state.models import (
    Mastery,
    OnboardingState,
    StepInAssessment,
    UserAdoptionState,
    WorkflowProgress,
)
from autoplay_sdk.user_adoption_state.onboarding_plan import (
    OnboardingPlan,
    OnboardingWorkflow,
    split_workflows,
)
from autoplay_sdk.user_adoption_state.tour_matching import (
    TourCatalogEntry,
    TourMatchResult,
    build_tour_match_input,
    parse_tour_match_output,
)
from autoplay_sdk.user_adoption_state.types import (
    JourneyState,
    MasteryLevel,
    WorkflowStatus,
)

__all__ = [
    "JourneyState",
    "MasteryLevel",
    "WorkflowStatus",
    "Mastery",
    "WorkflowProgress",
    "StepInAssessment",
    "OnboardingState",
    "UserAdoptionState",
    "ExplorationGateConfig",
    "evaluate_hard_gate",
    "OnboardingWorkflow",
    "OnboardingPlan",
    "split_workflows",
    "TourCatalogEntry",
    "TourMatchResult",
    "build_tour_match_input",
    "parse_tour_match_output",
]
