"""
Unit tests for CodingAgent._prepare_error_budget_pause and
CodingAgent._complete_error_budget_pause.

Uses the same minimal-agent construction pattern as
tests/core/test_parallel_tool_execution.py: bypass __init__ via
object.__new__ and inject mocks directly onto the instance.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.agent import CodingAgent


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _TaskState:
    """Minimal TaskState stub."""

    def __init__(self, resume_count=0, progress_since_resume=0):
        self.error_budget_resume_count = resume_count
        self.successful_tools_since_resume = progress_since_resume
        self.last_stop_reason = None

    def get_pending_summary(self):
        return []


class _ErrorTracker:
    """Minimal ErrorRecoveryTracker stub."""

    def __init__(self, total_failures=3):
        self._total_failures = total_failures
        self.reset_calls = []

    def get_stats(self):
        return {"total_failures": self._total_failures}

    def reset_tool_error_counts(self, tool_name=None):
        self.reset_calls.append(tool_name)


class _UIWithPause:
    """UI stub that has pause capability and returns a configurable PauseResult."""

    def __init__(self, continue_work=True, feedback=None):
        self._continue = continue_work
        self._feedback = feedback
        self.pause_calls = 0

    def has_pause_capability(self):
        return True

    async def wait_for_pause_response(self, timeout=None):
        from src.core.protocol import PauseResult
        self.pause_calls += 1
        return PauseResult(continue_work=self._continue, feedback=self._feedback)


class _UIWithoutPause:
    """UI stub that lacks pause capability (no has_pause_capability attribute)."""

    pass


class _CancellingUI:
    """UI stub whose wait_for_pause_response raises CancelledError."""

    def has_pause_capability(self):
        return True

    async def wait_for_pause_response(self, timeout=None):
        raise asyncio.CancelledError()


# ---------------------------------------------------------------------------
# Fixture: bare CodingAgent with mocks injected (no __init__)
# ---------------------------------------------------------------------------

@pytest.fixture
def make_agent():
    """
    Factory that builds a CodingAgent shell sufficient for testing the
    error-budget pause helpers.  Only the attributes accessed by those
    methods are wired.
    """
    def _factory(
        awaiting_approval=False,
        resume_count=0,
        progress_since_resume=0,
        total_failures=3,
    ):
        agent = object.__new__(CodingAgent)
        agent._awaiting_approval = awaiting_approval
        # The agent stores these as direct attributes (not via TaskState)
        agent._error_budget_resume_count = resume_count
        agent._successful_tools_since_resume = progress_since_resume
        agent.last_stop_reason = None
        agent._error_tracker = _ErrorTracker(total_failures=total_failures)
        # _build_pause_message is used by the fallback path; stub it out.
        agent._build_pause_message = MagicMock(return_value="[pause message]")
        # _get_pending_summary replaces task_state.get_pending_summary after refactor
        agent._get_pending_summary = MagicMock(return_value=[])
        return agent

    return _factory


# ---------------------------------------------------------------------------
# _prepare_error_budget_pause tests
# ---------------------------------------------------------------------------

COMMON_KWARGS = dict(
    reason="too many errors",
    tool_name="run_command",
    call_id="call_abc",
    error_context_block="<error>details</error>",
    tool_call_count=10,
    elapsed_seconds=45.0,
    max_resumes=2,
)


class TestPrepareErrorBudgetPause:
    """Tests for the synchronous preflight helper."""

    def test_defer_when_approval_pending(self, make_agent):
        """When _awaiting_approval is True, skip the pause entirely."""
        agent = make_agent(awaiting_approval=True)
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "defer"
        msg = result["tool_message"]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_abc"
        assert msg["name"] == "run_command"
        assert msg["content"] == "<error>details</error>"

    def test_cap_exceeded_when_resume_count_at_max(self, make_agent):
        """When resume_count >= max_resumes, stop with fallback text."""
        agent = make_agent(resume_count=2)  # == max_resumes=2
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "cap_exceeded"
        assert "fallback_text" in result
        assert "2" in result["fallback_text"]  # max_resumes appears in message

    def test_cap_exceeded_when_resume_count_exceeds_max(self, make_agent):
        """resume_count > max_resumes also triggers cap_exceeded (defensive)."""
        agent = make_agent(resume_count=5)
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "cap_exceeded"

    def test_interactive_path_normal(self, make_agent):
        """First pause with pause-capable UI returns interactive action."""
        agent = make_agent(resume_count=0)
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "interactive"
        assert result["pause_reason_code"] == "error_budget"
        assert "Error budget:" in result["pause_reason"]
        stats = result["pause_stats"]
        assert stats["tool_calls"] == 10
        assert stats["elapsed_s"] == 45.0
        assert stats["errors_total"] == 3

    def test_interactive_path_sets_last_stop_reason(self, make_agent):
        """last_stop_reason is set to 'error_budget' during prepare."""
        agent = make_agent(resume_count=0)
        ui = _UIWithPause()

        agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert agent.last_stop_reason == "error_budget"

    def test_interactive_no_progress_reason_code(self, make_agent):
        """After a resume with zero progress, reason_code becomes error_budget_no_progress."""
        agent = make_agent(resume_count=1, progress_since_resume=0)
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "interactive"
        assert result["pause_reason_code"] == "error_budget_no_progress"
        assert "no progress" in result["pause_reason"]

    def test_interactive_with_progress_keeps_normal_reason_code(self, make_agent):
        """After a resume with some progress, reason_code stays error_budget."""
        agent = make_agent(resume_count=1, progress_since_resume=3)
        ui = _UIWithPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "interactive"
        assert result["pause_reason_code"] == "error_budget"

    def test_fallback_when_ui_has_no_pause_capability(self, make_agent):
        """UI without has_pause_capability falls back to text message."""
        agent = make_agent(resume_count=0)
        ui = _UIWithoutPause()

        result = agent._prepare_error_budget_pause(**COMMON_KWARGS, ui=ui)

        assert result["action"] == "fallback"
        assert "fallback_text" in result
        agent._build_pause_message.assert_called_once_with("error_budget")


# ---------------------------------------------------------------------------
# _complete_error_budget_pause tests
# ---------------------------------------------------------------------------

COMPLETE_KWARGS = dict(
    tool_name="run_command",
    call_id="call_abc",
    error_context_block="<error>details</error>",
)


class TestCompleteErrorBudgetPause:
    """Tests for the async completion helper."""

    @pytest.mark.asyncio
    async def test_user_continues(self, make_agent):
        """When user chooses continue, state is reset and action='continue'."""
        agent = make_agent(resume_count=0)
        ui = _UIWithPause(continue_work=True, feedback=None)

        result = await agent._complete_error_budget_pause(**COMPLETE_KWARGS, ui=ui)

        assert result["action"] == "continue"
        assert result["pause_result"].continue_work is True
        assert result["user_rejected"] is False
        # State resets
        assert agent._error_budget_resume_count == 1
        assert agent._successful_tools_since_resume == 0
        assert "run_command" in agent._error_tracker.reset_calls
        # Tool message populated
        tm = result["tool_message"]
        assert tm["role"] == "tool"
        assert tm["tool_call_id"] == "call_abc"
        # System notice added
        assert any("Continuing after error budget" in m["content"]
                   for m in result["context_additions"])

    @pytest.mark.asyncio
    async def test_user_continues_with_feedback(self, make_agent):
        """Feedback from user is appended as a user message."""
        agent = make_agent(resume_count=0)
        ui = _UIWithPause(continue_work=True, feedback="try a different path")

        result = await agent._complete_error_budget_pause(**COMPLETE_KWARGS, ui=ui)

        assert result["action"] == "continue"
        guidance = [m for m in result["context_additions"] if m["role"] == "user"]
        assert len(guidance) == 1
        assert "try a different path" in guidance[0]["content"]

    @pytest.mark.asyncio
    async def test_user_stops(self, make_agent):
        """When user rejects, action='break' and user_rejected=True."""
        agent = make_agent(resume_count=0)
        ui = _UIWithPause(continue_work=False, feedback=None)

        result = await agent._complete_error_budget_pause(**COMPLETE_KWARGS, ui=ui)

        assert result["action"] == "break"
        assert result["user_rejected"] is True
        assert result["pause_result"].continue_work is False
        # No state mutations
        assert agent._error_budget_resume_count == 0
        assert len(agent._error_tracker.reset_calls) == 0

    @pytest.mark.asyncio
    async def test_cancelled_error_treated_as_stop(self, make_agent):
        """CancelledError normalises to a stop PauseResult -- pause_result is never None."""
        agent = make_agent(resume_count=0)
        ui = _CancellingUI()

        result = await agent._complete_error_budget_pause(**COMPLETE_KWARGS, ui=ui)

        # pause_result is always set (enables PausePromptEnd to always be emitted)
        assert result["pause_result"] is not None
        assert result["pause_result"].continue_work is False
        assert result["pause_result"].feedback == "Pause cancelled"
        assert result["action"] == "break"
        assert result["user_rejected"] is True

    @pytest.mark.asyncio
    async def test_cancelled_does_not_mutate_state(self, make_agent):
        """On cancellation the error tracker and resume count are not touched."""
        agent = make_agent(resume_count=1)
        ui = _CancellingUI()

        await agent._complete_error_budget_pause(**COMPLETE_KWARGS, ui=ui)

        assert agent._error_budget_resume_count == 1  # unchanged
        assert len(agent._error_tracker.reset_calls) == 0
