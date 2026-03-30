"""
Safety-net integration tests for agent tool loop paths.

These tests cover stream_response() - the async entry point used by the TUI.
They use the real LLM API (via .claraity/config.yaml) with simple prompts
that produce deterministic behavior (short answers, known tool calls).

Run with: pytest tests/core/test_tool_loop_integration.py -v
Skip if no API: tests auto-skip when API config is missing.
"""

import asyncio
import json
import os
import pytest

from src.core.events import (
    StreamStart, StreamEnd, TextDelta,
    PausePromptStart, PausePromptEnd,
)
from src.core.agent import CodingAgent

from tests.core.conftest import (
    MockUIProtocol,
    make_tool_call,
    requires_api,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def collect_events(agent, user_input, ui):
    """Run stream_response and collect all events into a list."""
    events = []
    async for event in agent.stream_response(user_input, ui):
        events.append(event)
    return events


def get_text(events):
    """Extract combined text from TextDelta events."""
    return "".join(
        e.content for e in events if isinstance(e, TextDelta) and e.content
    )


# ---------------------------------------------------------------------------
# Test 1: stream_response with no tools (pure text)
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponseNoTools:

    @pytest.mark.asyncio
    async def test_pure_text_response(self, live_agent):
        """Pure text response yields StreamStart, TextDelta(s), StreamEnd."""
        agent = live_agent()
        ui = MockUIProtocol()

        # Simple greeting - LLM should respond with text only, no tool calls
        events = await collect_events(agent, "Say hello in exactly 3 words.", ui)

        types = [type(e) for e in events]
        assert StreamStart in types, "Missing StreamStart"
        assert StreamEnd in types, "Missing StreamEnd"

        text = get_text(events)
        assert len(text) > 0, f"No text content in response. Events: {types}"


# ---------------------------------------------------------------------------
# Test 2: stream_response with tool call (read_file is auto-approved)
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponseSingleTool:

    @pytest.mark.asyncio
    async def test_tool_call_executes_and_loops(self, live_agent):
        """Tool call executes, result added to context, LLM called again."""
        agent = live_agent()
        ui = MockUIProtocol()

        # Ask agent to list files - should trigger list_directory tool
        events = await collect_events(
            agent,
            "List the files in the current directory using the list_directory tool. "
            "After seeing the result, respond with a short summary.",
            ui,
        )

        types = [type(e) for e in events]
        assert StreamStart in types
        assert StreamEnd in types

        text = get_text(events)
        # LLM should have some response after tool execution
        assert len(text) > 0


# ---------------------------------------------------------------------------
# Test 3: stream_response plan mode gate
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponsePlanModeGate:

    @pytest.mark.asyncio
    async def test_write_tool_gated_in_plan_mode(self, live_agent):
        """Write tools are gated in plan mode (LLM gets denial, doesn't crash)."""
        agent = live_agent(permission_mode="plan")

        # Activate plan mode with a plan file path
        agent.plan_mode_state.is_active = True
        agent.plan_mode_state.plan_file_path = (
            agent.working_directory / ".claraity" / "plans" / "test.md"
        )

        ui = MockUIProtocol()

        # Ask to write a file - should be gated, not crash
        events = await collect_events(
            agent,
            "Write the text 'hello' to a file called /tmp/test.txt using write_file tool.",
            ui,
        )

        types = [type(e) for e in events]
        assert StreamStart in types
        assert StreamEnd in types
        # Should complete without crash (gated response sent to LLM)


# ---------------------------------------------------------------------------
# Test 4: stream_response director gate
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponseDirectorGate:

    @pytest.mark.asyncio
    async def test_mutating_tool_gated_in_understand_phase(self, live_agent):
        """Mutating tool in UNDERSTAND phase is gated."""
        agent = live_agent()

        # Activate director in UNDERSTAND phase
        agent.director_adapter._is_active = True
        from src.director.adapter import DirectorPhase
        agent.director_adapter._phase = DirectorPhase.UNDERSTAND

        ui = MockUIProtocol()

        events = await collect_events(
            agent,
            "Write the text 'test' to /tmp/test.txt using write_file tool.",
            ui,
        )

        types = [type(e) for e in events]
        assert StreamStart in types
        assert StreamEnd in types


# ---------------------------------------------------------------------------
# Test 5: stream_response user rejection
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponseUserRejection:

    @pytest.mark.asyncio
    async def test_rejecting_approval_stops_loop(self, live_agent):
        """Rejecting a tool approval stops the loop gracefully."""
        agent = live_agent(permission_mode="normal")
        ui = MockUIProtocol(auto_approve=False)

        events = await collect_events(
            agent,
            "Write the text 'hello' to a file called test_reject.txt",
            ui,
        )

        types = [type(e) for e in events]
        assert StreamStart in types
        assert StreamEnd in types

        # If write_file was attempted, there should be an approval request
        # (LLM may or may not use write_file - both outcomes are valid)


# ---------------------------------------------------------------------------
# Test 6: stream_response oversized output
# ---------------------------------------------------------------------------

@requires_api
class TestStreamResponseOversizedOutput:

    @pytest.mark.asyncio
    async def test_oversized_output_returns_error_guidance(self, live_agent):
        """Output exceeding limit returns error guidance instead of crashing."""
        agent = live_agent()
        # Set very small limit to trigger oversized check
        agent._max_tool_output_chars = 10

        ui = MockUIProtocol()

        events = await collect_events(
            agent,
            "List the files in the current directory using list_directory tool.",
            ui,
        )

        types = [type(e) for e in events]
        assert StreamStart in types
        assert StreamEnd in types


# ---------------------------------------------------------------------------
# ToolLoopState unit tests (no API needed)
# ---------------------------------------------------------------------------

class TestToolLoopState:

    def test_initial_state(self):
        """ToolLoopState initializes with correct defaults."""
        from src.core.tool_loop_state import ToolLoopState

        state = ToolLoopState(current_context=[])

        assert state.tool_call_count == 0
        assert state.iteration == 0
        assert state.pause_continue_count == 0
        assert state.response_content == ""
        assert state.tool_calls is None
        assert state.tool_messages == []
        assert state.blocked_calls == []
        assert state.user_rejected is False
        assert state.provider_error is None
        assert state.MAX_TOOL_CALLS == 200
        assert state.ABSOLUTE_MAX_ITERATIONS == 50

    def test_reset_iteration(self):
        """reset_iteration clears per-iteration state, preserves counters."""
        from src.core.tool_loop_state import ToolLoopState

        state = ToolLoopState(current_context=[])
        state.response_content = "some text"
        state.tool_calls = [1, 2, 3]
        state.tool_messages = [{"role": "tool"}]
        state.blocked_calls.append("call_1")
        state.user_rejected = True
        state.provider_error = "timeout"
        state.tool_call_count = 5
        state.iteration = 3

        state.reset_iteration()

        assert state.response_content == ""
        assert state.tool_calls is None
        assert state.tool_messages == []
        assert state.blocked_calls == []
        assert state.user_rejected is False
        assert state.provider_error is None
        # Accumulated state preserved
        assert state.tool_call_count == 5
        assert state.iteration == 3

    def test_reset_budgets_after_continue(self):
        """reset_budgets_after_continue resets counters and bumps continue count."""
        from src.core.tool_loop_state import ToolLoopState

        state = ToolLoopState(current_context=[])
        state.tool_call_count = 100
        state.iteration = 25

        state.reset_budgets_after_continue()

        assert state.pause_continue_count == 1
        assert state.tool_call_count == 0
        assert state.iteration == 0

    def test_elapsed_seconds(self):
        """elapsed_seconds returns monotonic time since start."""
        import time
        from src.core.tool_loop_state import ToolLoopState

        state = ToolLoopState(current_context=[])
        time.sleep(0.05)

        assert state.elapsed_seconds >= 0.04
