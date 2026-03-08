"""Tests for Director Protocol state machine.

Slice 3: The train track switching system — every valid route works,
every invalid route is rejected, dashboard reports correctly.
"""

import pytest

from src.director.models import (
    DirectorPhase, ContextDocument, DirectorPlan, VerticalSlice, PhaseResult,
)
from src.director.errors import InvalidTransitionError


def _make_context(task="test task"):
    """Helper: minimal valid ContextDocument."""
    return ContextDocument(task_description=task)


def _make_plan(summary="test plan"):
    """Helper: minimal valid DirectorPlan."""
    return DirectorPlan(
        slices=[VerticalSlice(id=1, title="slice 1")],
        summary=summary,
    )


class TestInitialState:
    """Protocol starts in IDLE with nothing loaded."""

    def test_initial_phase_is_idle(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.phase == DirectorPhase.IDLE

    def test_initial_is_not_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.is_active is False

    def test_initial_task_is_none(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.task_description is None

    def test_initial_context_is_none(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.context is None

    def test_initial_plan_is_none(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.plan is None

    def test_initial_history_is_empty(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.phase_history == []


class TestStart:
    """start() pulls the train out of the station: IDLE -> UNDERSTAND."""

    def test_transitions_to_understand(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("Add health endpoint")
        assert p.phase == DirectorPhase.UNDERSTAND

    def test_stores_task_description(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("Add health endpoint")
        assert p.task_description == "Add health endpoint"

    def test_is_active_after_start(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        assert p.is_active is True

    def test_clears_previous_state(self):
        """Starting fresh clears any leftover context/plan."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        # Run a full cycle first
        p.start("old task")
        p.complete_understand(_make_context("old"))
        p.complete_plan(_make_plan("old"))
        p.approve_plan()
        p.reset()
        # Start fresh
        p.start("new task")
        assert p.context is None
        assert p.plan is None
        assert p.phase_history == []

    def test_start_from_non_idle_raises(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        with pytest.raises(InvalidTransitionError) as exc_info:
            p.start("another task")
        assert exc_info.value.current == DirectorPhase.UNDERSTAND
        assert exc_info.value.attempted == DirectorPhase.UNDERSTAND


class TestCompleteUnderstand:
    """complete_understand() delivers the scout report: UNDERSTAND -> PLAN."""

    def test_transitions_to_plan(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        assert p.phase == DirectorPhase.PLAN

    def test_stores_context(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        ctx = _make_context("my task")
        p.complete_understand(ctx)
        assert p.context is ctx

    def test_returns_phase_result(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        result = p.complete_understand(_make_context())
        assert isinstance(result, PhaseResult)
        assert result.phase == DirectorPhase.UNDERSTAND
        assert result.success is True

    def test_adds_to_history(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        assert len(p.phase_history) == 1
        assert p.phase_history[0].phase == DirectorPhase.UNDERSTAND

    def test_from_idle_raises(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        with pytest.raises(InvalidTransitionError):
            p.complete_understand(_make_context())


class TestFailUnderstand:
    """fail_understand() signals the scout couldn't complete: UNDERSTAND -> FAILED."""

    def test_transitions_to_failed(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.fail_understand("codebase too large")
        assert p.phase == DirectorPhase.FAILED

    def test_returns_failed_result(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        result = p.fail_understand("no access")
        assert result.success is False
        assert result.error == "no access"

    def test_not_active_after_failure(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.fail_understand("reason")
        assert p.is_active is False


class TestCompletePlan:
    """complete_plan() submits the blueprint: PLAN -> AWAITING_APPROVAL."""

    def test_transitions_to_awaiting_approval(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        assert p.phase == DirectorPhase.AWAITING_APPROVAL

    def test_stores_plan(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        plan = _make_plan("my plan")
        p.complete_plan(plan)
        assert p.plan is plan

    def test_returns_phase_result(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        result = p.complete_plan(_make_plan())
        assert result.phase == DirectorPhase.PLAN
        assert result.success is True

    def test_from_understand_raises(self):
        """Can't skip straight from UNDERSTAND to AWAITING_APPROVAL."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        with pytest.raises(InvalidTransitionError):
            p.complete_plan(_make_plan())


class TestFailPlan:
    """fail_plan() signals planning couldn't complete: PLAN -> FAILED."""

    def test_transitions_to_failed(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.fail_plan("empty task")
        assert p.phase == DirectorPhase.FAILED

    def test_returns_failed_result(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        result = p.fail_plan("can't decompose")
        assert result.success is False
        assert result.error == "can't decompose"


class TestApprovePlan:
    """approve_plan() gives the green light: AWAITING_APPROVAL -> EXECUTE."""

    def test_transitions_to_execute(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.approve_plan()
        assert p.phase == DirectorPhase.EXECUTE

    def test_clears_rejection_feedback(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reject_plan("needs more slices")
        p.complete_plan(_make_plan("revised"))
        p.approve_plan()
        assert p.rejection_feedback is None

    def test_from_plan_raises(self):
        """Can't approve before submitting the plan."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        with pytest.raises(InvalidTransitionError):
            p.approve_plan()


class TestRejectPlan:
    """reject_plan() sends it back for revision: AWAITING_APPROVAL -> PLAN."""

    def test_transitions_to_plan(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reject_plan("needs more slices")
        assert p.phase == DirectorPhase.PLAN

    def test_stores_feedback(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reject_plan("add error handling slice")
        assert p.rejection_feedback == "add error handling slice"

    def test_feedback_defaults_to_none(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reject_plan()
        assert p.rejection_feedback is None

    def test_revision_cycle(self):
        """reject -> revise -> resubmit -> approve works."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan("v1"))
        p.reject_plan("too few slices")
        assert p.phase == DirectorPhase.PLAN
        p.complete_plan(_make_plan("v2"))
        assert p.phase == DirectorPhase.AWAITING_APPROVAL
        p.approve_plan()
        assert p.phase == DirectorPhase.EXECUTE

    def test_double_rejection_cycle(self):
        """Two rejections then approve."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan("v1"))
        p.reject_plan("first feedback")
        p.complete_plan(_make_plan("v2"))
        p.reject_plan("second feedback")
        assert p.rejection_feedback == "second feedback"
        p.complete_plan(_make_plan("v3"))
        p.approve_plan()
        assert p.phase == DirectorPhase.EXECUTE


class TestInvalidTransitions:
    """Every illegal route raises InvalidTransitionError."""

    def test_idle_to_plan(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        with pytest.raises(InvalidTransitionError):
            p.complete_understand(_make_context())

    def test_idle_to_execute(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        with pytest.raises(InvalidTransitionError):
            p.approve_plan()

    def test_understand_to_awaiting_approval(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        with pytest.raises(InvalidTransitionError):
            p.complete_plan(_make_plan())

    def test_plan_to_execute(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        with pytest.raises(InvalidTransitionError):
            p.approve_plan()

    def test_failed_to_understand(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.fail_understand("reason")
        with pytest.raises(InvalidTransitionError):
            p.complete_understand(_make_context())


class TestReset:
    """reset() is the emergency stop — back to IDLE from anywhere."""

    def test_reset_from_understand(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.reset()
        assert p.phase == DirectorPhase.IDLE
        assert p.is_active is False

    def test_reset_from_plan(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.reset()
        assert p.phase == DirectorPhase.IDLE

    def test_reset_from_awaiting_approval(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reset()
        assert p.phase == DirectorPhase.IDLE

    def test_reset_from_failed(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.fail_understand("reason")
        p.reset()
        assert p.phase == DirectorPhase.IDLE

    def test_reset_clears_everything(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reset()
        assert p.task_description is None
        assert p.context is None
        assert p.plan is None
        assert p.phase_history == []
        assert p.rejection_feedback is None


class TestIsActive:
    """is_active is True for working phases, False for terminal states."""

    def test_idle_not_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        assert p.is_active is False

    def test_understand_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        assert p.is_active is True

    def test_plan_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        assert p.is_active is True

    def test_awaiting_approval_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        assert p.is_active is True

    def test_failed_not_active(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.fail_understand("reason")
        assert p.is_active is False


class TestGetStatus:
    """get_status() is the dashboard — snapshot of current state."""

    def test_idle_status(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        s = p.get_status()
        assert s["phase"] == "IDLE"
        assert s["is_active"] is False
        assert s["has_context"] is False
        assert s["has_plan"] is False
        assert s["total_slices"] == 0

    def test_after_understand_status(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        s = p.get_status()
        assert s["phase"] == "PLAN"
        assert s["task"] == "task"
        assert s["has_context"] is True
        assert s["has_plan"] is False
        assert s["phase_history_count"] == 1

    def test_after_plan_status(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        s = p.get_status()
        assert s["phase"] == "AWAITING_APPROVAL"
        assert s["has_plan"] is True
        assert s["total_slices"] == 1
        assert s["completed_slices"] == 0

    def test_rejection_feedback_in_status(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        p.reject_plan("add tests")
        s = p.get_status()
        assert s["rejection_feedback"] == "add tests"


class TestPhaseHistory:
    """phase_history accumulates results as phases complete."""

    def test_history_after_two_phases(self):
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        p.complete_plan(_make_plan())
        history = p.phase_history
        assert len(history) == 2
        assert history[0].phase == DirectorPhase.UNDERSTAND
        assert history[1].phase == DirectorPhase.PLAN

    def test_history_is_a_copy(self):
        """Modifying returned list doesn't affect protocol state."""
        from src.director.protocol import DirectorProtocol
        p = DirectorProtocol()
        p.start("task")
        p.complete_understand(_make_context())
        history = p.phase_history
        history.clear()
        assert len(p.phase_history) == 1
