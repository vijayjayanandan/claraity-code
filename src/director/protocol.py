"""
Director Protocol state machine.

The train track switching system — enforces which phase transitions
are legal and prevents derailments. Every transition is logged with
full context through the observability framework.
"""

from datetime import datetime
from typing import Any, Optional

from src.observability import get_logger

from .errors import InvalidTransitionError
from .models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
    PhaseResult,
)

logger = get_logger(__name__)


# The track map: from each phase, which phases can you reach?
VALID_TRANSITIONS: dict[DirectorPhase, set[DirectorPhase]] = {
    DirectorPhase.IDLE:              {DirectorPhase.UNDERSTAND},
    DirectorPhase.UNDERSTAND:        {DirectorPhase.PLAN, DirectorPhase.FAILED},
    DirectorPhase.PLAN:              {DirectorPhase.AWAITING_APPROVAL, DirectorPhase.FAILED},
    DirectorPhase.AWAITING_APPROVAL: {DirectorPhase.PLAN, DirectorPhase.EXECUTE, DirectorPhase.FAILED},
    DirectorPhase.EXECUTE:           {DirectorPhase.INTEGRATE, DirectorPhase.FAILED},
    DirectorPhase.INTEGRATE:         {DirectorPhase.COMPLETE, DirectorPhase.FAILED},
    DirectorPhase.COMPLETE:          {DirectorPhase.IDLE},
    DirectorPhase.FAILED:            {DirectorPhase.IDLE},
}


class DirectorProtocol:
    """
    State machine enforcing the Director Protocol workflow.

    IDLE -> UNDERSTAND -> PLAN -> AWAITING_APPROVAL -> EXECUTE -> INTEGRATE -> COMPLETE
    """

    def __init__(self) -> None:
        self._phase: DirectorPhase = DirectorPhase.IDLE
        self._task_description: str | None = None
        self._context: ContextDocument | None = None
        self._plan: DirectorPlan | None = None
        self._phase_history: list[PhaseResult] = []
        self._started_at: datetime | None = None
        self._rejection_feedback: str | None = None

    # -- Properties --

    @property
    def phase(self) -> DirectorPhase:
        return self._phase

    @property
    def task_description(self) -> str | None:
        return self._task_description

    @property
    def context(self) -> ContextDocument | None:
        return self._context

    @property
    def plan(self) -> DirectorPlan | None:
        return self._plan

    @property
    def phase_history(self) -> list[PhaseResult]:
        return list(self._phase_history)

    @property
    def is_active(self) -> bool:
        return self._phase not in (
            DirectorPhase.IDLE,
            DirectorPhase.COMPLETE,
            DirectorPhase.FAILED,
        )

    @property
    def rejection_feedback(self) -> str | None:
        return self._rejection_feedback

    # -- Internal transition engine --

    def _transition(self, target: DirectorPhase) -> None:
        """Attempt a state transition. Logs and raises on invalid routes."""
        valid = VALID_TRANSITIONS.get(self._phase, set())
        if target not in valid:
            logger.error(
                "invalid_director_transition",
                current=self._phase.name,
                attempted=target.name,
                task=self._task_description,
            )
            raise InvalidTransitionError(self._phase, target)
        old = self._phase
        self._phase = target
        logger.info(
            "director_transition",
            old_phase=old.name,
            new_phase=target.name,
            task=self._task_description,
        )

    # -- Phase transition methods --

    def start(self, task_description: str) -> None:
        """Start the protocol: IDLE -> UNDERSTAND."""
        self._transition(DirectorPhase.UNDERSTAND)
        self._task_description = task_description
        self._context = None
        self._plan = None
        self._phase_history = []
        self._started_at = datetime.now()
        self._rejection_feedback = None

    def complete_understand(self, context: ContextDocument) -> PhaseResult:
        """Scout report received: UNDERSTAND -> PLAN."""
        result = PhaseResult(
            phase=DirectorPhase.UNDERSTAND,
            success=True,
            output=context,
        )
        self._context = context
        self._phase_history.append(result)
        self._transition(DirectorPhase.PLAN)
        return result

    def fail_understand(self, reason: str) -> PhaseResult:
        """Scout couldn't complete: UNDERSTAND -> FAILED."""
        result = PhaseResult(
            phase=DirectorPhase.UNDERSTAND,
            success=False,
            error=reason,
        )
        self._phase_history.append(result)
        self._transition(DirectorPhase.FAILED)
        return result

    def complete_plan(self, plan: DirectorPlan) -> PhaseResult:
        """Blueprint submitted: PLAN -> AWAITING_APPROVAL."""
        result = PhaseResult(
            phase=DirectorPhase.PLAN,
            success=True,
            output=plan,
        )
        self._plan = plan
        self._phase_history.append(result)
        self._transition(DirectorPhase.AWAITING_APPROVAL)
        return result

    def fail_plan(self, reason: str) -> PhaseResult:
        """Planning couldn't complete: PLAN -> FAILED."""
        result = PhaseResult(
            phase=DirectorPhase.PLAN,
            success=False,
            error=reason,
        )
        self._phase_history.append(result)
        self._transition(DirectorPhase.FAILED)
        return result

    def approve_plan(self) -> None:
        """Human says go: AWAITING_APPROVAL -> EXECUTE."""
        self._rejection_feedback = None
        self._transition(DirectorPhase.EXECUTE)

    def reject_plan(self, feedback: str | None = None) -> None:
        """Human says revise: AWAITING_APPROVAL -> PLAN."""
        self._rejection_feedback = feedback
        self._transition(DirectorPhase.PLAN)

    def complete_integration(self) -> PhaseResult:
        """Final curtain: INTEGRATE -> COMPLETE."""
        result = PhaseResult(
            phase=DirectorPhase.INTEGRATE,
            success=True,
            output=None,
        )
        self._phase_history.append(result)
        self._transition(DirectorPhase.COMPLETE)
        return result

    def reset(self) -> None:
        """Emergency stop — return to IDLE from anywhere."""
        self._phase = DirectorPhase.IDLE
        self._task_description = None
        self._context = None
        self._plan = None
        self._phase_history = []
        self._started_at = None
        self._rejection_feedback = None

    # -- Status --

    def get_status(self) -> dict[str, Any]:
        """Dashboard readout — snapshot of current state."""
        return {
            "phase": self._phase.name,
            "task": self._task_description,
            "is_active": self.is_active,
            "has_context": self._context is not None,
            "has_plan": self._plan is not None,
            "total_slices": self._plan.total_slices if self._plan else 0,
            "completed_slices": self._plan.completed_slices if self._plan else 0,
            "phase_history_count": len(self._phase_history),
            "rejection_feedback": self._rejection_feedback,
        }
