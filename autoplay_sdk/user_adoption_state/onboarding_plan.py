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
from collections.abc import Iterable
from dataclasses import dataclass, field

from autoplay_sdk.user_adoption_state.activity_detector import ActivitySignals
from autoplay_sdk.user_adoption_state.models import WorkflowProgress
from autoplay_sdk.user_adoption_state.types import WorkflowStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowStep:
    """One target step within an onboarding workflow.

    Steps are *context and signal* for the agent: they describe what "done"
    typically looks like for a workflow so the LLM can recognise progress in
    the live activity stream. They are NOT a hard checklist — whether a
    workflow is complete remains the LLM's holistic judgement (reflected in
    ``WorkflowProgress.status``), so a user may finish a workflow via a
    variant path without every step being individually marked done.

    step_id     : stable identifier for the step (unique within a workflow).
    name        : human-readable name shown to the user / agent.
    description : what the step looks like, so the LLM can recognise it.
    required    : a HINT to the LLM about which steps are core vs.
                  nice-to-have. It informs the judgement but does not gate
                  completion — the LLM may still deem a workflow complete
                  without a "required" step when the outcome was clearly
                  achieved another way.
    activity_signals : OPTIONAL deterministic PostHog/activity-stream
                  signals for THIS individual step. Same shape and
                  semantics as :attr:`OnboardingWorkflow.activity_signals`
                  one level up — when an action stream satisfies any of
                  the step's signal rules, the step is marked COMPLETED
                  in :class:`WorkflowProgress.steps` via the pure
                  :func:`detect_completed_steps_from_activity` detector.
                  Steps with no signals fall back to the LLM's holistic
                  per-step inference (the prompt is fed the step list as
                  context regardless). Decoupled from workflow-level
                  ``activity_signals`` so a workflow can express
                  "completed" by ANY of its activity signals while still
                  letting per-step progress accumulate when finer-grained
                  rules fire — useful for the in-flight progress pill
                  the welcome runner surfaces.
    """

    step_id: str
    name: str = ""
    description: str = ""
    required: bool = True
    activity_signals: ActivitySignals | None = None

    def to_dict(self) -> dict:
        d: dict = {"step_id": self.step_id, "name": self.name}
        if self.description:
            d["description"] = self.description
        # Emit ``required`` only when it diverges from the default so the
        # serialised config stays compact and old consumers don't see a new
        # key for the common case.
        if not self.required:
            d["required"] = False
        if self.activity_signals is not None:
            d["activity_signals"] = self.activity_signals.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowStep:
        # ``or ""`` idiom (see ``OnboardingWorkflow.from_dict``): explicit
        # ``null`` values in config fall back to empty strings rather than
        # the literal "None".
        return cls(
            step_id=str(d["step_id"]),
            name=str(d.get("name") or ""),
            description=str(d.get("description") or ""),
            # Default True; only an explicit ``false`` makes a step optional.
            required=bool(d.get("required", True)),
            # Same defensive parse as the workflow-level signals — a
            # typo'd block parses to ``None`` (logged) so the step
            # degrades to LLM-only judgement rather than breaking the
            # whole workflow config load.
            activity_signals=ActivitySignals.from_dict(d.get("activity_signals")),
        )


def _parse_steps(raw: object) -> tuple[WorkflowStep, ...]:
    """Parse a workflow's ``steps`` config list into ``WorkflowStep`` objects.

    Defensive (mirrors :meth:`OnboardingPlan.from_config`): a malformed entry
    or one missing ``step_id`` is skipped with a warning rather than aborting
    the whole workflow parse.
    """
    if not isinstance(raw, list):
        return ()
    steps: list[WorkflowStep] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or not entry.get("step_id"):
            logger.warning("onboarding_plan: steps[%d] invalid — skipping", i)
            continue
        try:
            steps.append(WorkflowStep.from_dict(entry))
        except Exception as exc:  # noqa: BLE001 - defensive config parse
            logger.warning(
                "onboarding_plan: steps[%d] parse error — skipping: %s", i, exc
            )
    return tuple(steps)


@dataclass(frozen=True)
class OnboardingWorkflow:
    """One target onboarding workflow.

    workflow_id : tour id (matches a ``tour_registry`` entry).
    name        : human-readable name shown to the user / agent.
    description : what the workflow accomplishes (grounds the agent's reasoning).
    why         : WHY this workflow matters to the user — surfaced when the
                  agent suggests the flow ("I'm suggesting this because…")
                  and when it celebrates a completion ("nice work, here's why
                  that mattered"). Keeping it as a separate field from
                  ``description`` lets the prompt instruct the LLM to use
                  each one for a different rhetorical purpose: description
                  grounds the agent's understanding of what the flow does,
                  ``why`` grounds the user-facing pitch. Optional —
                  workflows shipped before this field existed silently fall
                  back to ``description``.
    role        : optional role gate; ``None`` means all roles.
    steps       : ordered target steps for this workflow. Optional — a
                  workflow with no declared steps behaves exactly as before
                  (the LLM judges completion from activity alone).
    prerequisite_workflow_ids : workflow ids that MUST be completed before
                  this workflow becomes eligible for suggestion. Empty
                  tuple = "always eligible". Used by both the welcome and
                  follow-up runners to filter out suggestions that don't
                  make sense yet (e.g. don't suggest "Configure columns"
                  to a brand-new admin who hasn't created a CAE product —
                  there are no columns to configure on an object that
                  doesn't exist). The chain is enforced AT THE PLAN
                  LEVEL — both the prompt (the LLM is told the eligible
                  set) and the runner (deterministic post-filter) refuse
                  to surface a workflow whose prereqs aren't all in
                  ``completed_workflow_ids``. Order within the tuple does
                  not matter; we check pure subset containment.
    activity_signals : optional :class:`ActivitySignals` block describing
                  deterministic PostHog/activity-stream patterns that
                  mark this workflow as complete WITHOUT the user having
                  finished the guided tour. Drives the eager workflow-
                  detection path in the forwarder (and the belt-and-
                  suspenders pre-pass in the welcome/follow-up runners),
                  so a user who creates a CAE in their own UI flow
                  jumps straight to "Configure columns" instead of
                  being re-suggested "Create your CAE". ``None`` keeps
                  pre-signals behaviour: completion is gated solely on
                  the tour-completed event + the LLM judge. Backward-
                  compatible — existing config blobs that don't carry
                  ``activity_signals`` parse and behave exactly as
                  before.
    """

    workflow_id: str
    name: str = ""
    description: str = ""
    why: str = ""
    role: str | None = None
    steps: tuple[WorkflowStep, ...] = ()
    prerequisite_workflow_ids: tuple[str, ...] = ()
    activity_signals: ActivitySignals | None = None

    @property
    def required_step_ids(self) -> list[str]:
        """Step ids the config marks as required (preserves declared order)."""
        return [s.step_id for s in self.steps if s.required]

    def to_dict(self) -> dict:
        d: dict = {"workflow_id": self.workflow_id, "name": self.name}
        if self.description:
            d["description"] = self.description
        if self.why:
            d["why"] = self.why
        if self.role is not None:
            d["role"] = self.role
        if self.steps:
            d["steps"] = [s.to_dict() for s in self.steps]
        if self.prerequisite_workflow_ids:
            # Serialize as a list for JSON friendliness — tuple is only
            # an in-memory choice (frozen dataclass needs hashable fields).
            d["prerequisite_workflow_ids"] = list(self.prerequisite_workflow_ids)
        if self.activity_signals is not None:
            d["activity_signals"] = self.activity_signals.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> OnboardingWorkflow:
        # ``str(d.get("name", ""))`` returns the literal "None" when the
        # config explicitly has ``"name": null`` (default kicks in only for
        # MISSING keys, not null values). Use the ``or ""`` idiom so
        # explicit nulls fall back to empty strings — what callers expect.
        # Strip the role string so trailing whitespace in config doesn't
        # leak into ``for_role`` comparisons (matched main's hardening).
        role_raw = d.get("role")
        role_norm = str(role_raw).strip() if role_raw is not None else ""
        # Prereqs: accept any iterable of strings, defensively coerce.
        # Tuple-cast because the parent dataclass is frozen and a list
        # field wouldn't be hashable. Empty / missing / wrong-shape ⇒ ().
        prereq_raw = d.get("prerequisite_workflow_ids")
        if isinstance(prereq_raw, (list, tuple)):
            prereqs = tuple(str(p).strip() for p in prereq_raw if str(p).strip())
        else:
            prereqs = ()
        # ActivitySignals parsing is delegated to its own ``from_dict``
        # which returns ``None`` on missing/malformed config (with a
        # logged warning per offending rule). Workflows whose signal
        # block fails to parse continue to function — they just won't
        # get the eager-completion treatment, so the system degrades to
        # the pre-signals (tour + judge) behaviour rather than failing
        # the whole product config load.
        signals = ActivitySignals.from_dict(d.get("activity_signals"))
        return cls(
            workflow_id=str(d["workflow_id"]),
            name=str(d.get("name") or ""),
            description=str(d.get("description") or ""),
            why=str(d.get("why") or ""),
            role=role_norm or None,
            steps=_parse_steps(d.get("steps")),
            prerequisite_workflow_ids=prereqs,
            activity_signals=signals,
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

    def next_eligible_workflows(
        self, completed_ids: Iterable[str]
    ) -> list[OnboardingWorkflow]:
        """Return workflows whose prereqs are met and that aren't completed.

        A workflow is eligible iff:

        1. It is NOT already in ``completed_ids``.
        2. Every entry in its ``prerequisite_workflow_ids`` IS in
           ``completed_ids``.

        Workflows with no declared prereqs are always eligible (as long as
        they aren't completed). Results are returned in the plan's declared
        order so callers that want "the single next step" can just take the
        first one — the declared order doubles as a priority signal when
        more than one workflow is simultaneously eligible.

        Centralised here (instead of duplicated across welcome / follow-up
        runners) so the LLM prompt input, the runner's deterministic
        post-filter, and any future call site stay in lockstep. If a
        workflow chain regresses (e.g. a config typo points to a prereq
        that doesn't exist) the chain silently truncates rather than
        deadlocks — we log a warning per dangling prereq so the operator
        can spot it without breaking onboarding for real users.
        """
        completed = {str(c).strip() for c in completed_ids if str(c).strip()}
        ids = set(self.workflow_ids)
        eligible: list[OnboardingWorkflow] = []
        for w in self.workflows:
            if w.workflow_id in completed:
                continue
            unmet = [p for p in w.prerequisite_workflow_ids if p not in completed]
            if unmet:
                # Soft warn on a dangling prereq id — almost certainly a
                # config typo, and silently treating it as "always unmet"
                # would deadlock the chain.
                for p in unmet:
                    if p not in ids:
                        logger.warning(
                            "onboarding_plan: workflow %r references unknown "
                            "prerequisite %r — chain may deadlock until config "
                            "is fixed",
                            w.workflow_id,
                            p,
                        )
                continue
            eligible.append(w)
        return eligible

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


def is_plan_complete(
    plan: OnboardingPlan,
    workflow_progress: dict[str, WorkflowProgress],
) -> bool:
    """True when every workflow in ``plan`` is COMPLETED per the LLM's judgement.

    A thin convenience wrapper over :func:`split_workflows` — it adds no new
    logic, just names the existing "no outstanding workflows" check. An empty
    plan is never "complete" (there is nothing to finish). Steps never gate
    this: completion is driven entirely by ``WorkflowProgress.status``.
    """
    if not plan.workflow_ids:
        return False
    _completed, _in_progress, outstanding = split_workflows(plan, workflow_progress)
    return not outstanding


def step_completion_ratio(
    workflow: OnboardingWorkflow,
    wp: WorkflowProgress | None,
) -> float:
    """Fraction of ``workflow``'s declared steps the LLM believes are COMPLETED.

    For display/telemetry only (e.g. a progress bar) — NEVER used to decide
    workflow or onboarding completion, which stays :func:`split_workflows` /
    ``WorkflowProgress.status``. Returns ``0.0`` when the workflow declares no
    steps so callers can render a neutral bar without special-casing.
    """
    total = len(workflow.steps)
    if total == 0:
        return 0.0
    if wp is None:
        return 0.0
    declared = {s.step_id for s in workflow.steps}
    done = sum(
        1
        for sid in declared
        if (sp := wp.steps.get(sid)) is not None
        and sp.status == WorkflowStatus.COMPLETED
    )
    return done / total
