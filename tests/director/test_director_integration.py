"""Tests for Director integration -- wiring into the agent.

Slice 4: Verifies the electrical wiring -- adapter exports, code writer
prompt, context builder injection, and __init__ exports.
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


class TestDirectorExports:
    """Updated __init__.py exports all Phase 2 components."""

    def test_adapter_importable(self):
        from src.director import DirectorAdapter
        assert DirectorAdapter is not None

    def test_gate_decision_importable(self):
        from src.director import DirectorGateDecision
        assert DirectorGateDecision is not None

    def test_tools_importable(self):
        from src.director import (
            DirectorCompleteUnderstandTool,
            DirectorCompletePlanTool,
            DirectorCompleteSliceTool,
        )
        assert DirectorCompleteUnderstandTool is not None
        assert DirectorCompletePlanTool is not None
        assert DirectorCompleteSliceTool is not None

    def test_prompts_importable(self):
        from src.director import PHASE_PROMPTS, PHASE_ALLOWED_TOOLS
        assert isinstance(PHASE_PROMPTS, dict)
        assert isinstance(PHASE_ALLOWED_TOOLS, dict)


class TestCodeWriterPrompt:
    """CODE_WRITER_PROMPT exists and follows the subagent pattern."""

    def test_prompt_exists(self):
        from src.prompts.subagents import CODE_WRITER_PROMPT
        assert isinstance(CODE_WRITER_PROMPT, str)
        assert len(CODE_WRITER_PROMPT) > 100

    def test_prompt_mentions_minimum_code(self):
        from src.prompts.subagents import CODE_WRITER_PROMPT
        prompt_lower = CODE_WRITER_PROMPT.lower()
        assert "minimum" in prompt_lower or "minimal" in prompt_lower

    def test_prompt_mentions_test(self):
        from src.prompts.subagents import CODE_WRITER_PROMPT
        prompt_lower = CODE_WRITER_PROMPT.lower()
        assert "test" in prompt_lower

    def test_prompt_mentions_existing_patterns(self):
        from src.prompts.subagents import CODE_WRITER_PROMPT
        prompt_lower = CODE_WRITER_PROMPT.lower()
        assert "pattern" in prompt_lower or "convention" in prompt_lower


class TestContextBuilderInjection:
    """Director prompt injection works through context_builder."""

    def test_build_context_accepts_director_adapter_param(self):
        """Verify the signature accepts director_adapter without error."""
        from src.core.context_builder import ContextBuilder
        import inspect
        sig = inspect.signature(ContextBuilder.build_context)
        assert "director_adapter" in sig.parameters

    def test_injection_included_when_adapter_active(self):
        """When director is active, injection text appears in system prompt."""
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        adapter.start("Add user authentication")

        injection = adapter.get_prompt_injection()
        assert injection is not None
        assert "UNDERSTAND" in injection
        assert "Add user authentication" in injection

    def test_no_injection_when_adapter_inactive(self):
        """When director is idle, no injection -- zero impact."""
        from src.director.adapter import DirectorAdapter
        adapter = DirectorAdapter()
        assert adapter.get_prompt_injection() is None


class TestDirectorAdapterLifecycleWithTools:
    """Full lifecycle using tools (not direct adapter methods)."""

    def test_understand_tool_then_plan_tool(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import (
            DirectorCompleteUnderstandTool,
            DirectorCompletePlanTool,
        )

        adapter = DirectorAdapter()
        understand_tool = DirectorCompleteUnderstandTool(adapter)
        plan_tool = DirectorCompletePlanTool(adapter)

        # Start
        adapter.start("Add /health endpoint")
        assert adapter.phase == DirectorPhase.UNDERSTAND

        # LLM calls director_complete_understand
        result = understand_tool.execute(
            task_description="Add /health endpoint",
            affected_files=["src/routes.py"],
            existing_patterns=["Flask blueprint"],
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.PLAN

        # LLM calls director_complete_plan
        result = plan_tool.execute(
            summary="One slice for health endpoint",
            slices=[{
                "title": "Health route",
                "files_to_create": ["src/health.py"],
                "files_to_modify": ["src/routes.py"],
                "test_criteria": ["GET /health returns 200"],
            }],
            plan_document=_make_plan_file(),
        )
        assert result.is_success()
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

    def test_full_cycle_through_execute(self):
        from src.director.adapter import DirectorAdapter
        from src.director.tools import (
            DirectorCompleteUnderstandTool,
            DirectorCompletePlanTool,
            DirectorCompleteSliceTool,
        )

        adapter = DirectorAdapter()
        understand = DirectorCompleteUnderstandTool(adapter)
        plan = DirectorCompletePlanTool(adapter)
        slice_tool = DirectorCompleteSliceTool(adapter)

        # UNDERSTAND
        adapter.start("Add auth")
        understand.execute(task_description="Add auth")
        assert adapter.phase == DirectorPhase.PLAN

        # PLAN
        plan.execute(
            summary="Two slices",
            slices=[
                {"title": "User model"},
                {"title": "Login route"},
            ],
            plan_document=_make_plan_file(),
        )
        assert adapter.phase == DirectorPhase.AWAITING_APPROVAL

        # APPROVE
        adapter.approve_plan()
        assert adapter.phase == DirectorPhase.EXECUTE

        # EXECUTE slice 1
        result = slice_tool.execute(slice_id=1, test_results_summary="5 passed")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.EXECUTE

        # EXECUTE slice 2
        result = slice_tool.execute(slice_id=2, test_results_summary="8 passed")
        assert result.is_success()
        assert adapter.phase == DirectorPhase.INTEGRATE
