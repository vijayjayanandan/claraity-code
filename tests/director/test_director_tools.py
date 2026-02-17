"""Tests for Director checkpoint tools.

Slice 3: The checkpoint stations -- actor shows work, stage manager
validates and either advances to next scene or returns an error.
"""

import os
import tempfile

import pytest

from src.director.models import (
    DirectorPhase,
    ContextDocument,
    DirectorPlan,
    VerticalSlice,
)


def _make_plan_file(content: str = "# Test Plan\n\nTest plan content.") -> str:
    """Create a temporary plan file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".md", prefix="director_plan_")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return path

# NOTE: ToolResult/ToolStatus imported locally inside tests to avoid
# circular import through src.tools -> src.llm chain.


class TestToolConstruction:
    """Each tool constructs correctly with adapter reference."""

    def test_complete_understand_tool_creates(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompleteUnderstandTool
        adapter = DirectorAdapter()
        tool = DirectorCompleteUnderstandTool(adapter)
        assert tool.name == "director_complete_understand"

    def test_complete_plan_tool_creates(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompletePlanTool
        adapter = DirectorAdapter()
        tool = DirectorCompletePlanTool(adapter)
        assert tool.name == "director_complete_plan"

    def test_complete_slice_tool_creates(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompleteSliceTool
        adapter = DirectorAdapter()
        tool = DirectorCompleteSliceTool(adapter)
        assert tool.name == "director_complete_slice"

    def test_tools_have_schemas(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import (
            DirectorCompleteUnderstandTool,
            DirectorCompletePlanTool,
            DirectorCompleteSliceTool,
        )
        adapter = DirectorAdapter()
        for ToolClass in (
            DirectorCompleteUnderstandTool,
            DirectorCompletePlanTool,
            DirectorCompleteSliceTool,
        ):
            tool = ToolClass(adapter)
            schema = tool.get_schema()
            assert "name" in schema
            assert "parameters" in schema


class TestCompleteUnderstandTool:
    """director_complete_understand: UNDERSTAND -> PLAN."""

    @pytest.fixture
    def setup(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompleteUnderstandTool
        adapter = DirectorAdapter()
        tool = DirectorCompleteUnderstandTool(adapter)
        return adapter, tool

    def test_happy_path_transitions_to_plan(self, setup):
        adapter, tool = setup
        adapter.start("Add auth")
        result = tool.execute(
            task_description="Add auth",
            affected_files=["src/auth.py"],
            existing_patterns=["Flask blueprint"],
            constraints=["no emojis"],
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.PLAN

    def test_minimal_input(self, setup):
        adapter, tool = setup
        adapter.start("Add auth")
        result = tool.execute(task_description="Add auth")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.PLAN

    def test_wrong_phase_returns_error(self, setup):
        adapter, tool = setup
        # Don't start -- still in IDLE
        result = tool.execute(task_description="Add auth")
        assert not result.is_success()
        assert "phase" in result.error.lower() or "UNDERSTAND" in result.error

    def test_missing_task_description_returns_error(self, setup):
        adapter, tool = setup
        adapter.start("Add auth")
        result = tool.execute()
        assert not result.is_success()


class TestCompletePlanTool:
    """director_complete_plan: PLAN -> AWAITING_APPROVAL."""

    @pytest.fixture
    def setup(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompletePlanTool
        adapter = DirectorAdapter()
        tool = DirectorCompletePlanTool(adapter)
        # Get to PLAN phase
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        return adapter, tool

    def test_happy_path_transitions_to_awaiting_approval(self, setup):
        adapter, tool = setup
        result = tool.execute(
            summary="Two slices for auth",
            slices=[
                {"title": "Login route", "files_to_modify": ["src/routes.py"]},
                {"title": "Middleware", "test_criteria": ["auth required"]},
            ],
            plan_document=_make_plan_file(),
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

    def test_single_slice(self, setup):
        adapter, tool = setup
        result = tool.execute(
            summary="One slice",
            slices=[{"title": "Add endpoint"}],
            plan_document=_make_plan_file(),
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

    def test_wrong_phase_returns_error(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompletePlanTool
        adapter = DirectorAdapter()
        tool = DirectorCompletePlanTool(adapter)
        adapter.start("Add auth")
        # Still in UNDERSTAND, not PLAN
        result = tool.execute(
            summary="s", slices=[{"title": "s1"}],
            plan_document=_make_plan_file(),
        )
        assert not result.is_success()

    def test_empty_slices_returns_error(self, setup):
        adapter, tool = setup
        result = tool.execute(summary="No slices", slices=[], plan_document=_make_plan_file())
        assert not result.is_success()

    def test_missing_slices_returns_error(self, setup):
        adapter, tool = setup
        result = tool.execute(summary="No slices field", plan_document=_make_plan_file())
        assert not result.is_success()


class TestCompleteSliceTool:
    """director_complete_slice: marks slice done, advances or integrates."""

    @pytest.fixture
    def setup(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompleteSliceTool
        adapter = DirectorAdapter()
        tool = DirectorCompleteSliceTool(adapter)
        # Get to EXECUTE phase
        adapter.start("Add auth")
        context = ContextDocument(task_description="Add auth")
        adapter.complete_understand(context)
        plan = DirectorPlan(
            summary="Two slices",
            slices=[
                VerticalSlice(id=1, title="Login route"),
                VerticalSlice(id=2, title="Middleware"),
            ],
        )
        adapter.complete_plan(plan)
        adapter.approve_plan()
        return adapter, tool

    def test_complete_first_slice_stays_in_execute(self, setup):
        adapter, tool = setup
        result = tool.execute(
            slice_id=1,
            test_results_summary="3 passed",
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.EXECUTE

    def test_complete_all_slices_transitions_to_integrate(self, setup):
        adapter, tool = setup
        # Complete slice 1
        tool.execute(slice_id=1, test_results_summary="3 passed")
        assert adapter.phase == DirectorPhase.EXECUTE
        # Complete slice 2
        result = tool.execute(slice_id=2, test_results_summary="5 passed")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.INTEGRATE

    def test_wrong_phase_returns_error(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import DirectorCompleteSliceTool
        adapter = DirectorAdapter()
        tool = DirectorCompleteSliceTool(adapter)
        adapter.start("Add auth")
        # Still in UNDERSTAND, not EXECUTE
        result = tool.execute(slice_id=1, test_results_summary="ok")
        assert not result.is_success()

    def test_missing_slice_id_returns_error(self, setup):
        adapter, tool = setup
        result = tool.execute(test_results_summary="ok")
        assert not result.is_success()
