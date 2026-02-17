"""Tests for Director activation via /director command and plan approval flow.

Verifies:
- /director command activates the adapter
- /director-reset resets to IDLE
- director_complete_plan triggers approval flow
- Approval calls adapter.approve_plan()
- Rejection calls adapter.reject_plan(feedback)
"""

import os
import tempfile

import pytest

from src.director.adapter import DirectorAdapter, DirectorGateDecision
from src.director.models import DirectorPhase
from src.director.tools import (
    DirectorCompleteUnderstandTool,
    DirectorCompletePlanTool,
    DirectorCompleteSliceTool,
)


def _make_plan_file(content: str = "# Test Plan\n\nTest plan content.") -> str:
    """Create a temporary plan file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".md", prefix="director_plan_")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return path


# =============================================================================
# /director command activation
# =============================================================================

class TestDirectorCommandActivation:
    """Tests for /director command parsing and adapter activation."""

    def test_start_activates_adapter(self):
        """adapter.start() puts adapter into UNDERSTAND phase."""
        adapter = DirectorAdapter()
        adapter.start("Add user authentication")
        assert adapter.phase == DirectorPhase.UNDERSTAND
        assert adapter.is_active

    def test_start_stores_task(self):
        adapter = DirectorAdapter()
        adapter.start("Build REST API")
        status = adapter.get_status()
        assert status["task"] == "Build REST API"

    def test_prompt_injection_active_after_start(self):
        """After start, the LLM sees UNDERSTAND phase prompt."""
        adapter = DirectorAdapter()
        adapter.start("Add caching")
        injection = adapter.get_prompt_injection()
        assert injection is not None
        assert "UNDERSTAND" in injection
        assert "Add caching" in injection

    def test_gating_active_after_start(self):
        """After start, write tools are gated."""
        adapter = DirectorAdapter()
        adapter.start("task")
        assert adapter.gate_tool("write_file") == DirectorGateDecision.DENY
        assert adapter.gate_tool("read_file") == DirectorGateDecision.ALLOW


# =============================================================================
# /director-reset command
# =============================================================================

class TestDirectorResetCommand:
    """Tests for /director-reset command."""

    def test_reset_returns_to_idle(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE
        assert not adapter.is_active

    def test_reset_clears_gating(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        assert adapter.gate_tool("write_file") == DirectorGateDecision.DENY

        adapter.reset()
        assert adapter.gate_tool("write_file") == DirectorGateDecision.ALLOW

    def test_reset_clears_injection(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        assert adapter.get_prompt_injection() is not None

        adapter.reset()
        assert adapter.get_prompt_injection() is None


# =============================================================================
# Approval flow (unit tests for the approval logic)
# =============================================================================

class TestDirectorApprovalFlow:
    """Tests for the plan approval step in director mode."""

    def _advance_to_awaiting_approval(self):
        """Helper: advance adapter to AWAITING_APPROVAL."""
        adapter = DirectorAdapter()
        understand = DirectorCompleteUnderstandTool(adapter)
        plan = DirectorCompletePlanTool(adapter)

        adapter.start("Build feature")
        understand.execute(task_description="Build feature")
        plan_file = _make_plan_file()
        plan.execute(
            plan_document=plan_file,
            summary="Two slices",
            slices=[
                {"title": "Data model"},
                {"title": "API route"},
            ],
        )
        return adapter

    def test_reaches_awaiting_approval(self):
        adapter = self._advance_to_awaiting_approval()
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

    def test_approve_transitions_to_execute(self):
        adapter = self._advance_to_awaiting_approval()
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_reject_transitions_to_plan(self):
        adapter = self._advance_to_awaiting_approval()
        adapter.reject_plan("Too broad")
        assert adapter.phase == DirectorPhase.PLAN

    def test_reject_with_feedback_stored(self):
        adapter = self._advance_to_awaiting_approval()
        adapter.reject_plan("Split into smaller slices")
        status = adapter.get_status()
        assert status["rejection_feedback"] == "Split into smaller slices"

    def test_reject_without_feedback(self):
        adapter = self._advance_to_awaiting_approval()
        adapter.reject_plan(None)
        assert adapter.phase == DirectorPhase.PLAN

    def test_approve_sets_first_slice_as_current(self):
        adapter = self._advance_to_awaiting_approval()
        adapter.approve_plan()
        status = adapter.get_status()
        assert status["current_slice_id"] == 1

    def test_awaiting_approval_prompt_content(self):
        """In AWAITING_APPROVAL, prompt tells LLM to wait."""
        adapter = self._advance_to_awaiting_approval()
        injection = adapter.get_prompt_injection()
        assert injection is not None
        assert "AWAITING_APPROVAL" in injection


# =============================================================================
# Full activation + approval + execution flow
# =============================================================================

class TestDirectorActivationE2E:
    """End-to-end: /director command through to EXECUTE phase."""

    def test_full_activation_to_execute(self):
        """Simulates: /director task → UNDERSTAND → PLAN → approve → EXECUTE."""
        adapter = DirectorAdapter()
        understand = DirectorCompleteUnderstandTool(adapter)
        plan = DirectorCompletePlanTool(adapter)
        slice_tool = DirectorCompleteSliceTool(adapter)

        # /director Add search
        adapter.start("Add search")
        assert adapter.phase == DirectorPhase.UNDERSTAND

        # LLM explores and completes understand
        understand.execute(task_description="Add search")
        assert adapter.phase == DirectorPhase.PLAN

        # LLM creates plan
        plan_file = _make_plan_file()
        plan.execute(
            plan_document=plan_file,
            summary="One slice",
            slices=[{"title": "Search endpoint"}],
        )
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # User approves (via widget or /approve)
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

        # LLM implements slice
        result = slice_tool.execute(slice_id=1, test_results_summary="3 passed")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.INTEGRATE

    def test_rejection_then_approve_to_execute(self):
        """Simulates: plan → reject → revise → approve → execute."""
        adapter = DirectorAdapter()
        understand = DirectorCompleteUnderstandTool(adapter)
        plan = DirectorCompletePlanTool(adapter)

        adapter.start("Add auth")
        understand.execute(task_description="Add auth")

        # First plan rejected
        plan_file = _make_plan_file("# Plan v1")
        plan.execute(plan_document=plan_file, summary="v1", slices=[{"title": "Everything"}])
        adapter.reject_plan("Too broad")
        assert adapter.phase == DirectorPhase.PLAN

        # Revised plan approved
        plan_file2 = _make_plan_file("# Plan v2\nRevised.")
        plan.execute(
            plan_document=plan_file2,
            summary="v2",
            slices=[
                {"title": "User model"},
                {"title": "Login route"},
            ],
        )
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE


# =============================================================================
# CLI command parsing simulation
# =============================================================================

class TestDirectorCommandParsing:
    """Tests simulating the /director command parsing logic."""

    def test_parse_director_command(self):
        """Verify /director <task> parsing extracts task correctly."""
        user_input = "/director Add user authentication"
        assert user_input.lower().startswith("/director ")
        task = user_input[len("/director "):].strip()
        assert task == "Add user authentication"

    def test_parse_director_no_task(self):
        """Verify /director with no task is detected."""
        user_input = "/director"
        assert user_input.lower().startswith("/director")
        task = user_input[len("/director"):].strip()
        assert task == ""

    def test_parse_director_reset(self):
        """Verify /director-reset command."""
        user_input = "/director-reset"
        assert user_input.lower() == "/director-reset"

    def test_parse_director_extra_whitespace(self):
        """Handles extra whitespace in command."""
        user_input = "/director   Build REST API  "
        task = user_input[len("/director"):].strip()
        assert task == "Build REST API"
