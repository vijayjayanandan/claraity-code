"""Tests for Director phase prompts and tool allowlists.

Slice 1: The script for each act — validates that every phase has
the right instructions and the right tools available.
"""

import pytest

from src.director.models import DirectorPhase, ContextDocument, DirectorPlan, VerticalSlice


class TestPhasePromptsExist:
    """Every active phase must have a system prompt script."""

    def test_understand_phase_has_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.UNDERSTAND in PHASE_PROMPTS

    def test_plan_phase_has_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.PLAN in PHASE_PROMPTS

    def test_awaiting_approval_phase_has_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.AWAITING_APPROVAL in PHASE_PROMPTS

    def test_execute_phase_has_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.EXECUTE in PHASE_PROMPTS

    def test_integrate_phase_has_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.INTEGRATE in PHASE_PROMPTS

    def test_idle_has_no_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.IDLE not in PHASE_PROMPTS

    def test_complete_has_no_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.COMPLETE not in PHASE_PROMPTS

    def test_failed_has_no_prompt(self):
        from src.director.prompts import PHASE_PROMPTS
        assert DirectorPhase.FAILED not in PHASE_PROMPTS


class TestPhasePromptsContent:
    """Prompts mention the correct checkpoint tool for their phase."""

    def test_understand_prompt_mentions_checkpoint_tool(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.UNDERSTAND]
        assert "director_complete_understand" in prompt

    def test_understand_prompt_forbids_code_writing(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.UNDERSTAND].lower()
        assert "do not write code" in prompt or "do not modify" in prompt

    def test_plan_prompt_mentions_checkpoint_tool(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.PLAN]
        assert "director_complete_plan" in prompt

    def test_plan_prompt_mentions_vertical_slices(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.PLAN].lower()
        assert "slice" in prompt

    def test_execute_prompt_mentions_checkpoint_tool(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.EXECUTE]
        assert "director_complete_slice" in prompt

    def test_execute_prompt_mentions_red_green_refactor(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.EXECUTE].lower()
        assert "red" in prompt and "green" in prompt

    def test_execute_prompt_instructs_delegation(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.EXECUTE].lower()
        assert "delegate" in prompt
        assert "test-writer" in prompt
        assert "code-writer" in prompt
        assert "code-reviewer" in prompt

    def test_execute_prompt_forbids_direct_coding(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.EXECUTE].lower()
        assert "do not write code" in prompt or "not write code yourself" in prompt

    def test_integrate_prompt_mentions_test_suite(self):
        from src.director.prompts import PHASE_PROMPTS
        prompt = PHASE_PROMPTS[DirectorPhase.INTEGRATE].lower()
        assert "test" in prompt


class TestGetDirectorPhasePrompt:
    """Dynamic prompt generation with context, plan, and slice info."""

    def test_returns_string(self):
        from src.director.prompts import get_director_phase_prompt
        result = get_director_phase_prompt(
            phase=DirectorPhase.UNDERSTAND,
            task_description="Add auth",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_task_description(self):
        from src.director.prompts import get_director_phase_prompt
        result = get_director_phase_prompt(
            phase=DirectorPhase.UNDERSTAND,
            task_description="Add user authentication",
        )
        assert "Add user authentication" in result

    def test_plan_phase_includes_context_summary(self):
        from src.director.prompts import get_director_phase_prompt
        context = ContextDocument(
            task_description="Add auth",
            existing_patterns=["Flask blueprint pattern"],
            constraints=["no emojis"],
        )
        result = get_director_phase_prompt(
            phase=DirectorPhase.PLAN,
            task_description="Add auth",
            context=context,
        )
        assert "Flask blueprint pattern" in result

    def test_execute_phase_includes_plan_summary(self):
        from src.director.prompts import get_director_phase_prompt
        plan = DirectorPlan(
            summary="Two slices for auth",
            slices=[
                VerticalSlice(id=1, title="Login route"),
                VerticalSlice(id=2, title="Protected middleware"),
            ],
        )
        result = get_director_phase_prompt(
            phase=DirectorPhase.EXECUTE,
            task_description="Add auth",
            plan=plan,
        )
        assert "Two slices for auth" in result

    def test_execute_phase_includes_current_slice(self):
        from src.director.prompts import get_director_phase_prompt
        plan = DirectorPlan(
            summary="Two slices",
            slices=[
                VerticalSlice(id=1, title="Login route"),
                VerticalSlice(id=2, title="Protected middleware"),
            ],
        )
        result = get_director_phase_prompt(
            phase=DirectorPhase.EXECUTE,
            task_description="Add auth",
            plan=plan,
            current_slice_id=1,
        )
        assert "Login route" in result

    def test_idle_returns_none(self):
        from src.director.prompts import get_director_phase_prompt
        result = get_director_phase_prompt(
            phase=DirectorPhase.IDLE,
            task_description="anything",
        )
        assert result is None

    def test_failed_returns_none(self):
        from src.director.prompts import get_director_phase_prompt
        result = get_director_phase_prompt(
            phase=DirectorPhase.FAILED,
            task_description="anything",
        )
        assert result is None


class TestPhaseAllowedTools:
    """Tool allowlists restrict dangerous tools in exploration phases."""

    def test_understand_allows_read_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "read_file" in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_understand_allows_search_code(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "search_code" in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_understand_allows_glob(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "glob" in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_understand_allows_director_checkpoint(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "director_complete_understand" in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_understand_blocks_write_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "write_file" not in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_understand_blocks_edit_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "edit_file" not in PHASE_ALLOWED_TOOLS[DirectorPhase.UNDERSTAND]

    def test_plan_blocks_write_file_in_allowlist(self):
        """write_file NOT in allowlist; adapter handles path-based gating."""
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "write_file" not in PHASE_ALLOWED_TOOLS[DirectorPhase.PLAN]

    def test_plan_allows_director_checkpoint(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "director_complete_plan" in PHASE_ALLOWED_TOOLS[DirectorPhase.PLAN]

    def test_execute_allows_write_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "write_file" in PHASE_ALLOWED_TOOLS[DirectorPhase.EXECUTE]

    def test_execute_allows_edit_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "edit_file" in PHASE_ALLOWED_TOOLS[DirectorPhase.EXECUTE]

    def test_execute_allows_run_command(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "run_command" in PHASE_ALLOWED_TOOLS[DirectorPhase.EXECUTE]

    def test_execute_allows_delegation(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "delegate_to_subagent" in PHASE_ALLOWED_TOOLS[DirectorPhase.EXECUTE]

    def test_execute_allows_director_checkpoint(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "director_complete_slice" in PHASE_ALLOWED_TOOLS[DirectorPhase.EXECUTE]

    def test_integrate_allows_run_command(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "run_command" in PHASE_ALLOWED_TOOLS[DirectorPhase.INTEGRATE]

    def test_integrate_blocks_write_file(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert "write_file" not in PHASE_ALLOWED_TOOLS[DirectorPhase.INTEGRATE]

    def test_idle_has_no_allowlist(self):
        from src.director.prompts import PHASE_ALLOWED_TOOLS
        assert DirectorPhase.IDLE not in PHASE_ALLOWED_TOOLS
