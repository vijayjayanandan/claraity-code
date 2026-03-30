"""Tests for Director Adapter — the stage manager.

Slice 2: Validates tool gating per phase, prompt injection per phase,
lifecycle transitions, and reset behavior.
"""

import pytest

from src.director.models import (
    DirectorPhase,
    ContextDocument,
    DirectorPlan,
    VerticalSlice,
    FileMapping,
)


class TestDirectorGateDecision:
    """The ALLOW/DENY enum exists and works."""

    def test_allow_exists(self):
        from src.director.adapter import DirectorGateDecision
        assert DirectorGateDecision.ALLOW.value == "allow"

    def test_deny_exists(self):
        from src.director.adapter import DirectorGateDecision
        assert DirectorGateDecision.DENY.value == "deny"


class TestGatingWhenInactive:
    """When director is IDLE, everything is allowed — zero impact."""

    def test_idle_allows_write_file(self):
        from src.director.adapter import DirectorAdapter, DirectorGateDecision
        adapter = DirectorAdapter()
        assert adapter.gate_tool("write_file") == DirectorGateDecision.ALLOW

    def test_idle_allows_read_file(self):
        from src.director.adapter import DirectorAdapter, DirectorGateDecision
        adapter = DirectorAdapter()
        assert adapter.gate_tool("read_file") == DirectorGateDecision.ALLOW

    def test_idle_allows_run_command(self):
        from src.director.adapter import DirectorAdapter, DirectorGateDecision
        adapter = DirectorAdapter()
        assert adapter.gate_tool("run_command") == DirectorGateDecision.ALLOW

    def test_is_active_false_when_idle(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        assert adapter.is_active is False

    def test_phase_is_idle(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        assert adapter.phase == DirectorPhase.IDLE


class TestGatingInUnderstandPhase:
    """UNDERSTAND phase: read-only + checkpoint. No writes."""

    @pytest.fixture
    def adapter_in_understand(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add authentication")
        return adapter

    def test_allows_read_file(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("read_file") == DirectorGateDecision.ALLOW

    def test_allows_search_code(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("search_code") == DirectorGateDecision.ALLOW

    def test_allows_glob(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("glob") == DirectorGateDecision.ALLOW

    def test_allows_checkpoint_tool(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("director_complete_understand") == DirectorGateDecision.ALLOW

    def test_denies_write_file(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("write_file") == DirectorGateDecision.DENY

    def test_denies_edit_file(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("edit_file") == DirectorGateDecision.DENY

    def test_denies_run_command(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("run_command") == DirectorGateDecision.DENY

    def test_denies_delegation(self, adapter_in_understand):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_understand.gate_tool("delegate_to_subagent") == DirectorGateDecision.DENY


class TestGatingInPlanPhase:
    """PLAN phase: read-only + delegation + checkpoint. No direct writes."""

    @pytest.fixture
    def adapter_in_plan(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add authentication")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        return adapter

    def test_allows_read_file(self, adapter_in_plan):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("read_file") == DirectorGateDecision.ALLOW

    def test_allows_search_code(self, adapter_in_plan):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("search_code") == DirectorGateDecision.ALLOW

    def test_allows_delegation(self, adapter_in_plan):
        """PLAN phase should allow delegating to planner subagent."""
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("delegate_to_subagent") == DirectorGateDecision.ALLOW

    def test_allows_checkpoint_tool(self, adapter_in_plan):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("director_complete_plan") == DirectorGateDecision.ALLOW

    def test_allows_write_file_for_plan_docs(self, adapter_in_plan):
        """write_file allowed only for .claraity/plans/ paths."""
        from src.director.adapter import DirectorGateDecision
        result = adapter_in_plan.gate_tool(
            "write_file",
            {"file_path": ".claraity/plans/director_plan.md"}
        )
        assert result == DirectorGateDecision.ALLOW

    def test_denies_write_file_for_other_paths(self, adapter_in_plan):
        """write_file denied for non-plan paths."""
        from src.director.adapter import DirectorGateDecision
        result = adapter_in_plan.gate_tool(
            "write_file",
            {"file_path": "src/main.py"}
        )
        assert result == DirectorGateDecision.DENY

    def test_denies_edit_file(self, adapter_in_plan):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("edit_file") == DirectorGateDecision.DENY

    def test_denies_run_command(self, adapter_in_plan):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_plan.gate_tool("run_command") == DirectorGateDecision.DENY


class TestGatingInExecutePhase:
    """EXECUTE phase: all tools available."""

    @pytest.fixture
    def adapter_in_execute(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        plan = DirectorPlan(
            summary="One slice",
            slices=[VerticalSlice(id=1, title="Login route")],
        )
        adapter.complete_plan(plan)
        adapter.approve_plan()
        return adapter

    def test_allows_write_file(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("write_file") == DirectorGateDecision.ALLOW

    def test_allows_edit_file(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("edit_file") == DirectorGateDecision.ALLOW

    def test_allows_run_command(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("run_command") == DirectorGateDecision.ALLOW

    def test_allows_delegation(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("delegate_to_subagent") == DirectorGateDecision.ALLOW

    def test_allows_read_file(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("read_file") == DirectorGateDecision.ALLOW

    def test_allows_checkpoint(self, adapter_in_execute):
        from src.director.adapter import DirectorGateDecision
        assert adapter_in_execute.gate_tool("director_complete_slice") == DirectorGateDecision.ALLOW


class TestPromptInjection:
    """Prompt injection returns the right content for each phase."""

    def test_idle_returns_none(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        assert adapter.get_prompt_injection() is None

    def test_understand_returns_string(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        injection = adapter.get_prompt_injection()
        assert isinstance(injection, str)
        assert "UNDERSTAND" in injection

    def test_understand_includes_task(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add user authentication")
        injection = adapter.get_prompt_injection()
        assert "Add user authentication" in injection

    def test_plan_includes_context(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        context = ContextDocument(
            task_description="Add auth",
            existing_patterns=["Flask blueprint"],
        )
        adapter.complete_understand(context)
        injection = adapter.get_prompt_injection()
        assert "PLAN" in injection
        assert "Flask blueprint" in injection

    def test_execute_includes_plan(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        plan = DirectorPlan(
            summary="Two slices for auth",
            slices=[VerticalSlice(id=1, title="Login")],
        )
        adapter.complete_plan(plan)
        adapter.approve_plan()
        injection = adapter.get_prompt_injection()
        assert "EXECUTE" in injection
        assert "Two slices for auth" in injection


class TestLifecycle:
    """Full lifecycle: start -> understand -> plan -> approve -> execute."""

    def test_full_happy_path(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()

        # Start
        adapter.start("Add /health endpoint")
        assert adapter.phase == DirectorPhase.UNDERSTAND
        assert adapter.is_active is True

        # Complete understand
        context = ContextDocument(task_description="Add /health endpoint")
        adapter.complete_understand(context)
        assert adapter.phase == DirectorPhase.PLAN

        # Complete plan
        plan = DirectorPlan(
            summary="One slice",
            slices=[VerticalSlice(id=1, title="Health route")],
        )
        adapter.complete_plan(plan)
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # Approve
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_rejection_cycle(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)

        # Plan v1
        plan_v1 = DirectorPlan(
            summary="v1", slices=[VerticalSlice(id=1, title="All-in-one")],
        )
        adapter.complete_plan(plan_v1)
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # Reject
        adapter.reject_plan("Too coarse")
        assert adapter.phase == DirectorPhase.PLAN

        # Plan v2
        plan_v2 = DirectorPlan(
            summary="v2",
            slices=[
                VerticalSlice(id=1, title="Model"),
                VerticalSlice(id=2, title="Route"),
            ],
        )
        adapter.complete_plan(plan_v2)
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_get_status(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Test task")
        status = adapter.get_status()
        assert status["phase"] == "UNDERSTAND"
        assert status["task"] == "Test task"
        assert status["is_active"] is True


class TestReset:
    """Reset returns to normal agent behavior at any point."""

    def test_reset_from_understand(self):
        from src.director.adapter import DirectorAdapter, DirectorGateDecision
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        assert adapter.is_active is True

        adapter.reset()
        assert adapter.is_active is False
        assert adapter.phase == DirectorPhase.IDLE
        assert adapter.get_prompt_injection() is None
        assert adapter.gate_tool("write_file") == DirectorGateDecision.ALLOW

    def test_reset_from_execute(self):
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        plan = DirectorPlan(
            summary="s", slices=[VerticalSlice(id=1, title="s1")],
        )
        adapter.complete_plan(plan)
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

        adapter.reset()
        assert adapter.phase == DirectorPhase.IDLE
        assert adapter.is_active is False
