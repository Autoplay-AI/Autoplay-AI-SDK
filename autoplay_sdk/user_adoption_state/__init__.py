"""Per-user adoption state: journey + mastery + onboarding lifecycle.

Orthogonal to the per-session ``AgentStateV2`` FSM. Keyed by ``user_id`` and
persisted by the connector. See :mod:`autoplay_sdk.user_adoption_state.models`.
"""

from autoplay_sdk.user_adoption_state.activity_detector import (
    ActivityMatch,
    ActivitySignalRule,
    ActivitySignals,
    StepActivityMatch,
    detect_completed_steps_from_activity,
    detect_completed_workflows_from_activity,
)
from autoplay_sdk.user_adoption_state.exploration_gate import (
    ExplorationGateConfig,
    evaluate_hard_gate,
)
from autoplay_sdk.user_adoption_state.models import (
    COMPLETION_RATE_DENOMINATOR_ALL_CATALOG,
    COMPLETION_RATE_DENOMINATOR_ASSIGNED,
    WORKFLOW_PROGRESS_SOURCE_ACTIVITY,
    WORKFLOW_PROGRESS_SOURCE_FOLLOWUP,
    WORKFLOW_PROGRESS_SOURCE_JUDGE,
    WORKFLOW_PROGRESS_SOURCE_MANUAL,
    WORKFLOW_PROGRESS_SOURCE_TOUR,
    WORKFLOW_PROGRESS_SOURCE_UNKNOWN,
    Mastery,
    OnboardingState,
    SessionIndexEntry,
    SessionSnapshot,
    StepInAssessment,
    StepProgress,
    UserAdoptionState,
    WorkflowProgress,
)
from autoplay_sdk.user_adoption_state.onboarding_plan import (
    OnboardingPlan,
    OnboardingWorkflow,
    WorkflowStep,
    is_plan_complete,
    split_workflows,
    step_completion_ratio,
)
from autoplay_sdk.user_adoption_state.session_summary import (
    build_onboarding_summary_input,
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
    "StepProgress",
    "WORKFLOW_PROGRESS_SOURCE_TOUR",
    "WORKFLOW_PROGRESS_SOURCE_ACTIVITY",
    "WORKFLOW_PROGRESS_SOURCE_JUDGE",
    "WORKFLOW_PROGRESS_SOURCE_FOLLOWUP",
    "WORKFLOW_PROGRESS_SOURCE_MANUAL",
    "WORKFLOW_PROGRESS_SOURCE_UNKNOWN",
    "COMPLETION_RATE_DENOMINATOR_ALL_CATALOG",
    "COMPLETION_RATE_DENOMINATOR_ASSIGNED",
    "StepInAssessment",
    "OnboardingState",
    "SessionIndexEntry",
    "SessionSnapshot",
    "UserAdoptionState",
    "ExplorationGateConfig",
    "evaluate_hard_gate",
    "OnboardingWorkflow",
    "WorkflowStep",
    "OnboardingPlan",
    "split_workflows",
    "is_plan_complete",
    "step_completion_ratio",
    "ActivitySignalRule",
    "ActivitySignals",
    "ActivityMatch",
    "StepActivityMatch",
    "detect_completed_workflows_from_activity",
    "detect_completed_steps_from_activity",
    "TourCatalogEntry",
    "TourMatchResult",
    "build_tour_match_input",
    "parse_tour_match_output",
    "build_onboarding_summary_input",
]
