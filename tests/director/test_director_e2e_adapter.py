"""End-to-end tests for Director Adapter lifecycle.

Slice 5: The final dress rehearsal -- exercises the full Director Adapter
from IDLE through COMPLETE, verifying gating, injection, and state at
every phase transition.
"""

import os
import tempfile

import pytest

from src.director.adapter import DirectorAdapter, DirectorGateDecision
from src.director.models import DirectorPhase, SliceStatus
from src.director.tools import (
    DirectorCompleteUnderstandTool,
    DirectorCompletePlanTool,
    DirectorCompleteSliceTool,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_plan_file(content: str = "# Test Plan\n\nTest plan content.") -> str:
    """Create a temporary plan file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".md", prefix="director_plan_")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return path


def _make_adapter_with_tools():
    """Create adapter + all 3 checkpoint tools."""
    adapter = DirectorAdapter()
    understand = DirectorCompleteUnderstandTool(adapter)
    plan = DirectorCompletePlanTool(adapter)
    slice_tool = DirectorCompleteSliceTool(adapter)
    return adapter, understand, plan, slice_tool


def _advance_to_execute(adapter, understand, plan):
    """Helper: advance adapter from IDLE to EXECUTE phase."""
    adapter.start("Build login page")
    understand.execute(
        task_description="Build login page",
        affected_files=["src/auth.py", "src/templates/login.html"],
        existing_patterns=["Flask blueprint", "Jinja2 templates"],
    )
    plan.execute(
        summary="Two slices: model + route",
        slices=[
            {
                "title": "User model",
                "files_to_create": ["src/models/user.py"],
                "files_to_modify": [],
                "test_criteria": ["User model has email and password fields"],
            },
            {
                "title": "Login route",
                "files_to_create": [],
                "files_to_modify": ["src/routes.py"],
                "test_criteria": ["POST /login returns 200 with valid creds"],
            },
        ],
        plan_document=_make_plan_file(),
    )
    adapter.approve_plan()


# =============================================================================
# Full Happy Path
# =============================================================================

class TestFullHappyPath:
    """Walk through every phase from IDLE to INTEGRATE."""

    def test_idle_to_understand(self):
        adapter, _, _, _ = _make_adapter_with_tools()
        assert adapter.phase == DirectorPhase.IDLE
        assert not adapter.is_active

        adapter.start("Add search feature")
        assert adapter.phase == DirectorPhase.UNDERSTAND
        assert adapter.is_active

    def test_understand_to_plan(self):
        adapter, understand, _, _ = _make_adapter_with_tools()
        adapter.start("Add search feature")

        result = understand.execute(
            task_description="Add search feature",
            affected_files=["src/search.py"],
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.PLAN

    def test_plan_to_awaiting_approval(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        adapter.start("Add search feature")
        understand.execute(task_description="Add search feature")

        result = plan.execute(
            summary="One slice for search",
            slices=[{"title": "Search endpoint"}],
            plan_document=_make_plan_file(),
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

    def test_approve_to_execute(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        adapter.start("Add search feature")
        understand.execute(task_description="Add search feature")
        plan.execute(
            summary="One slice",
            slices=[{"title": "Search endpoint"}],
            plan_document=_make_plan_file(),
        )

        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_execute_single_slice_to_integrate(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        adapter.start("Add search feature")
        understand.execute(task_description="Add search feature")
        plan.execute(
            summary="One slice",
            slices=[{"title": "Search endpoint"}],
            plan_document=_make_plan_file(),
        )
        adapter.approve_plan()

        result = slice_tool.execute(slice_id=1, test_results_summary="3 passed")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.INTEGRATE

    def test_execute_multi_slice_incremental(self):
        """Two slices: first stays in EXECUTE, second transitions to INTEGRATE."""
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)

        # Complete slice 1 -- should stay in EXECUTE
        result1 = slice_tool.execute(slice_id=1, test_results_summary="5 passed")
        assert result1.is_success()
        assert adapter.phase == DirectorPhase.EXECUTE

        # Complete slice 2 -- should transition to INTEGRATE
        result2 = slice_tool.execute(slice_id=2, test_results_summary="8 passed")
        assert result2.is_success()
        assert adapter.phase == DirectorPhase.INTEGRATE

    def test_full_lifecycle_status_progression(self):
        """Verify get_status() reflects correct state at each transition."""
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()

        # IDLE
        status = adapter.get_status()
        assert status["phase"] == "IDLE"
        assert status["is_active"] is False

        # UNDERSTAND
        adapter.start("Build API")
        status = adapter.get_status()
        assert status["phase"] == "UNDERSTAND"
        assert status["task"] == "Build API"

        # PLAN
        understand.execute(task_description="Build API")
        assert adapter.get_status()["phase"] == "PLAN"

        # AWAITING_APPROVAL
        plan.execute(summary="One slice", slices=[{"title": "API route"}], plan_document=_make_plan_file())
        assert adapter.get_status()["phase"] == "AWAITING_APPROVAL"

        # EXECUTE
        adapter.approve_plan()
        assert adapter.get_status()["phase"] == "EXECUTE"

        # INTEGRATE
        slice_tool.execute(slice_id=1, test_results_summary="all pass")
        assert adapter.get_status()["phase"] == "INTEGRATE"


# =============================================================================
# Rejection Cycle
# =============================================================================

class TestRejectionCycle:
    """Plan rejected with feedback, revised, then approved."""

    def test_reject_revise_approve(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        adapter.start("Add caching")
        understand.execute(task_description="Add caching")

        # First plan
        plan.execute(summary="Bad plan", slices=[{"title": "Cache everything"}], plan_document=_make_plan_file())
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # Reject
        adapter.reject_plan("Too broad -- split into targeted slices")
        assert adapter.phase == DirectorPhase.PLAN

        # Revised plan
        plan.execute(
            summary="Targeted caching",
            slices=[
                {"title": "Cache user queries"},
                {"title": "Cache search results"},
            ],
            plan_document=_make_plan_file(),
        )
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # Approve
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_double_rejection(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        adapter.start("Add caching")
        understand.execute(task_description="Add caching")

        # First plan -> reject
        plan.execute(summary="Plan v1", slices=[{"title": "v1"}], plan_document=_make_plan_file())
        adapter.reject_plan("Nope")

        # Second plan -> reject again
        plan.execute(summary="Plan v2", slices=[{"title": "v2"}], plan_document=_make_plan_file())
        adapter.reject_plan("Still not right")

        # Third plan -> approve
        plan.execute(summary="Plan v3", slices=[{"title": "v3"}], plan_document=_make_plan_file())
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE


# =============================================================================
# Tool Gating by Phase
# =============================================================================

class TestToolGatingByPhase:
    """Systematically verify gating across all active phases."""

    READ_TOOLS = ["read_file", "search_code", "glob", "list_directory"]
    WRITE_TOOLS = ["write_file", "edit_file"]
    EXEC_TOOLS = ["run_command"]

    def test_idle_allows_everything(self):
        adapter = DirectorAdapter()
        for tool in self.READ_TOOLS + self.WRITE_TOOLS + self.EXEC_TOOLS:
            assert adapter.gate_tool(tool) == DirectorGateDecision.ALLOW

    def test_understand_allows_reads_and_its_checkpoint(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        for tool in self.READ_TOOLS:
            assert adapter.gate_tool(tool) == DirectorGateDecision.ALLOW, f"{tool} should be allowed"
        # Only the understand checkpoint is allowed in UNDERSTAND
        assert adapter.gate_tool("director_complete_understand") == DirectorGateDecision.ALLOW

    def test_understand_denies_writes_and_exec(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        for tool in self.WRITE_TOOLS + self.EXEC_TOOLS:
            assert adapter.gate_tool(tool) == DirectorGateDecision.DENY, f"{tool} should be denied"

    def test_plan_write_file_path_restricted(self):
        """write_file allowed in PLAN only for .clarity/plans/ paths."""
        adapter, understand, _, _ = _make_adapter_with_tools()
        adapter.start("task")
        understand.execute(task_description="task")
        assert adapter.phase == DirectorPhase.PLAN

        # write_file allowed for plan docs
        assert adapter.gate_tool(
            "write_file", {"file_path": ".clarity/plans/director_plan.md"}
        ) == DirectorGateDecision.ALLOW

        # write_file denied for other paths
        assert adapter.gate_tool(
            "write_file", {"file_path": "src/main.py"}
        ) == DirectorGateDecision.DENY

        # write_file denied without args (no path to check)
        assert adapter.gate_tool("write_file") == DirectorGateDecision.DENY

        # edit_file still denied in PLAN
        assert adapter.gate_tool("edit_file") == DirectorGateDecision.DENY

    def test_execute_allows_reads_writes_exec_and_slice_checkpoint(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        assert adapter.phase == DirectorPhase.EXECUTE

        all_tools = (
            self.READ_TOOLS + self.WRITE_TOOLS + self.EXEC_TOOLS
            + ["director_complete_slice"]
        )
        for tool in all_tools:
            assert adapter.gate_tool(tool) == DirectorGateDecision.ALLOW, f"{tool} should be allowed in EXECUTE"

    def test_integrate_denies_writes(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        # Complete all slices to reach INTEGRATE
        slice_tool.execute(slice_id=1, test_results_summary="pass")
        slice_tool.execute(slice_id=2, test_results_summary="pass")
        assert adapter.phase == DirectorPhase.INTEGRATE

        for tool in self.WRITE_TOOLS:
            assert adapter.gate_tool(tool) == DirectorGateDecision.DENY, f"{tool} should be denied in INTEGRATE"

    def test_integrate_allows_reads_and_exec(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        slice_tool.execute(slice_id=1, test_results_summary="pass")
        slice_tool.execute(slice_id=2, test_results_summary="pass")
        assert adapter.phase == DirectorPhase.INTEGRATE

        for tool in self.READ_TOOLS:
            assert adapter.gate_tool(tool) == DirectorGateDecision.ALLOW, f"{tool} should be allowed in INTEGRATE"
        assert adapter.gate_tool("run_command") == DirectorGateDecision.ALLOW


# =============================================================================
# Prompt Injection by Phase
# =============================================================================

class TestPromptInjectionByPhase:
    """Verify correct prompt content in every phase."""

    def test_idle_no_injection(self):
        adapter = DirectorAdapter()
        assert adapter.get_prompt_injection() is None

    def test_understand_injection_content(self):
        adapter = DirectorAdapter()
        adapter.start("Build REST API")
        injection = adapter.get_prompt_injection()

        assert injection is not None
        assert "UNDERSTAND" in injection
        assert "Build REST API" in injection
        assert "director_complete_understand" in injection

    def test_plan_injection_content(self):
        adapter, understand, _, _ = _make_adapter_with_tools()
        adapter.start("Build REST API")
        understand.execute(
            task_description="Build REST API",
            affected_files=["src/api.py"],
        )
        injection = adapter.get_prompt_injection()

        assert injection is not None
        assert "PLAN" in injection
        assert "Build REST API" in injection

    def test_execute_injection_includes_plan(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        injection = adapter.get_prompt_injection()

        assert injection is not None
        assert "EXECUTE" in injection
        assert "Build login page" in injection

    def test_injection_changes_after_transition(self):
        """Injection content updates when phase changes."""
        adapter, understand, _, _ = _make_adapter_with_tools()
        adapter.start("Test task")

        understand_injection = adapter.get_prompt_injection()
        assert "UNDERSTAND" in understand_injection

        understand.execute(task_description="Test task")
        plan_injection = adapter.get_prompt_injection()
        assert "PLAN" in plan_injection
        assert understand_injection != plan_injection


# =============================================================================
# Reset Behavior
# =============================================================================

class TestResetBehavior:
    """Verify clean reset from any phase."""

    def test_reset_from_understand(self):
        adapter = DirectorAdapter()
        adapter.start("task")
        assert adapter.is_active

        adapter.reset()
        assert not adapter.is_active
        assert adapter.phase == DirectorPhase.IDLE
        assert adapter.get_prompt_injection() is None

    def test_reset_from_plan(self):
        adapter, understand, _, _ = _make_adapter_with_tools()
        adapter.start("task")
        understand.execute(task_description="task")
        assert adapter.phase == DirectorPhase.PLAN

        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE

    def test_reset_from_execute(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        assert adapter.phase == DirectorPhase.EXECUTE

        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE
        assert not adapter.is_active

    def test_reset_from_integrate(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)
        slice_tool.execute(slice_id=1, test_results_summary="pass")
        slice_tool.execute(slice_id=2, test_results_summary="pass")
        assert adapter.phase == DirectorPhase.INTEGRATE

        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE

    def test_reset_allows_fresh_start(self):
        """After reset, can start a completely new Director session."""
        adapter, understand, plan, _ = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)

        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE

        # Start fresh
        adapter.start("New task")
        assert adapter.phase == DirectorPhase.UNDERSTAND
        assert adapter.is_active

    def test_gating_reverts_after_reset(self):
        """After reset, no tools are gated."""
        adapter = DirectorAdapter()
        adapter.start("task")
        # write_file is denied in UNDERSTAND
        assert adapter.gate_tool("write_file") == DirectorGateDecision.DENY

        adapter.reset()
        # After reset, everything is allowed (IDLE)
        assert adapter.gate_tool("write_file") == DirectorGateDecision.ALLOW


# =============================================================================
# Director Inactive = Zero Impact
# =============================================================================

class TestDirectorInactiveZeroImpact:
    """When director is not active, it has zero impact on agent behavior."""

    def test_inactive_gate_allows_all_tools(self):
        adapter = DirectorAdapter()
        dangerous_tools = [
            "write_file", "edit_file", "run_command",
            "delete_file", "some_unknown_tool",
        ]
        for tool in dangerous_tools:
            assert adapter.gate_tool(tool) == DirectorGateDecision.ALLOW

    def test_inactive_no_prompt_injection(self):
        adapter = DirectorAdapter()
        assert adapter.get_prompt_injection() is None

    def test_inactive_status_reflects_idle(self):
        adapter = DirectorAdapter()
        status = adapter.get_status()
        assert status["phase"] == "IDLE"
        assert status["is_active"] is False

    def test_after_reset_behaves_like_fresh(self):
        """An adapter that was active then reset behaves identically to a fresh one."""
        used = DirectorAdapter()
        used.start("old task")
        used.reset()

        fresh = DirectorAdapter()

        assert used.phase == fresh.phase
        assert used.is_active == fresh.is_active
        assert used.get_prompt_injection() == fresh.get_prompt_injection()
        assert used.gate_tool("write_file") == fresh.gate_tool("write_file")


# =============================================================================
# Slice Status Tracking
# =============================================================================

class TestSliceStatusTracking:
    """Verify slice statuses are tracked correctly through EXECUTE phase."""

    def test_slices_start_as_pending(self):
        adapter, understand, plan, _ = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)

        status = adapter.get_status()
        assert status["total_slices"] == 2
        assert status["completed_slices"] == 0

    def test_completed_slice_count_increments(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)

        slice_tool.execute(slice_id=1, test_results_summary="pass")
        status = adapter.get_status()
        assert status["completed_slices"] == 1

    def test_all_slices_completed_count(self):
        adapter, understand, plan, slice_tool = _make_adapter_with_tools()
        _advance_to_execute(adapter, understand, plan)

        slice_tool.execute(slice_id=1, test_results_summary="pass")
        slice_tool.execute(slice_id=2, test_results_summary="pass")
        # After all slices complete, phase transitions to INTEGRATE
        assert adapter.phase == DirectorPhase.INTEGRATE
        status = adapter.get_status()
        assert status["completed_slices"] == 2
        assert status["total_slices"] == 2
