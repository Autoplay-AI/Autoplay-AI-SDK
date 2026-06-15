"""Target onboarding workflows the agent is told a user must complete.

Configured per product (and optionally per role) in
``integration_config.onboarding_workflows``. Each ``workflow_id`` lines up with
a ``tour_registry`` / ``proactive_intercom`` tour id so a suggested workflow can
be delivered as a "show me" tour offer.

This module is pure: parsing + a deterministic ``split_workflows`` guardrail.
Whether a workflow is actually complete is an LLM judgement that lives in
``WorkflowProgress`` (see :mod:`autoplay_sdk.user_adoption_state.models`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from autoplay_sdk.user_adoption_state.models import WorkflowProgress
from autoplay_sdk.user_adoption_state.types import WorkflowStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnboardingWorkflow:
    """One target onboarding workflow.

    workflow_id : tour id (matches a ``tour_registry`` entry).
    name        : human-readable name shown to the user / agent.
    description : what the workflow accomplishes (grounds the agent's reasoning).
    role        : optional role gate; ``None`` means all roles.
    """

    workflow_id: str
    name: str = ""
    description: str = ""
    role: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"workflow_id": self.workflow_id, "name": self.name}
        if self.description:
            d["description"] = self.description
        if self.role is not None:
            d["role"] = self.role
        return d

    @classmethod
    def from_dict(cls, d: dict) -> OnboardingWorkflow:
        name = d.get("name")
        description = d.get("description")
        role = d.get("role")
        role_norm = str(role).strip() if role is not None else ""
        return cls(
            workflow_id=str(d["workflow_id"]),
            name=str(name) if name is not None else "",
            description=str(description) if description is not None else "",
            role=role_norm or None,
        )


@dataclass
class OnboardingPlan:
    """The set of target onboarding workflows for a product."""

    workflows: list[OnboardingWorkflow] = field(default_factory=list)

    @property
    def workflow_ids(self) -> list[str]:
        return [w.workflow_id for w in self.workflows]

    def for_role(self, role: str | None) -> OnboardingPlan:
        """Return a plan filtered to workflows visible to ``role``.

        A workflow with ``role is None`` is visible to everyone; otherwise it is
        only included when its role matches ``role`` (case-insensitive).
        """
        norm = (role or "").strip().lower()
        kept = [
            w
            for w in self.workflows
            if w.role is None or w.role.strip().lower() == norm
        ]
        return OnboardingPlan(workflows=kept)

    @classmethod
    def from_config(cls, raw: object) -> OnboardingPlan:
        """Parse ``integration_config.onboarding_workflows`` (a list of dicts)."""
        workflows: list[OnboardingWorkflow] = []
        if isinstance(raw, list):
            for i, entry in enumerate(raw):
                if not isinstance(entry, dict) or not entry.get("workflow_id"):
                    logger.warning(
                        "onboarding_plan: workflows[%d] invalid — skipping", i
                    )
                    continue
                try:
                    workflows.append(OnboardingWorkflow.from_dict(entry))
                except Exception as exc:  # noqa: BLE001 - defensive config parse
                    logger.warning(
                        "onboarding_plan: workflows[%d] parse error — skipping: %s",
                        i,
                        exc,
                    )
        return cls(workflows=workflows)


def split_workflows(
    plan: OnboardingPlan,
    workflow_progress: dict[str, WorkflowProgress],
) -> tuple[list[str], list[str], list[str]]:
    """Bucket plan workflow ids into ``(completed, in_progress, outstanding)``.

    Deterministic prefilter/guardrail only — the authoritative completion call is
    the LLM's, reflected in ``WorkflowProgress.status``.
    """
    completed: list[str] = []
    in_progress: list[str] = []
    outstanding: list[str] = []
    for wid in plan.workflow_ids:
        wp = workflow_progress.get(wid)
        status = wp.status if wp else WorkflowStatus.NOT_STARTED
        if status == WorkflowStatus.COMPLETED:
            completed.append(wid)
        elif status == WorkflowStatus.IN_PROGRESS:
            in_progress.append(wid)
            outstanding.append(wid)
        else:
            outstanding.append(wid)
    return completed, in_progress, outstanding
