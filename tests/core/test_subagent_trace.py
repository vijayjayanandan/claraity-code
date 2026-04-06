"""
Tests for subagent trace visualization feature.

Coverage:
- TraceIntegration: on_subagent_start / on_subagent_end emission and no-ops
- DelegateToSubagentTool: set_trace wiring
- SubprocessInput: trace_enabled field serialization
- SubAgent: trace calls fire in correct order during execute
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# TraceIntegration bookend methods
# ---------------------------------------------------------------------------


class TestSubagentBookendEmission:
    """on_subagent_start and on_subagent_end emit correct events."""

    def _make_trace(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._emitter = MagicMock()
        return ti

    def test_on_subagent_start_emits(self):
        ti = self._make_trace()
        ti.on_subagent_start("code-reviewer", "Review auth.py", "/tmp/trace.jsonl")

        ti._emitter.emit.assert_called_once()
        args, kwargs = ti._emitter.emit.call_args
        assert args[0] == "agent"  # from
        assert args[1] == "agent"  # to
        assert "code-reviewer" in args[2]  # label
        assert args[3] == "subagent_start"  # step_type
        assert kwargs["sections"]["trace_path"] == "/tmp/trace.jsonl"
        assert kwargs["sections"]["subagent_name"] == "code-reviewer"

    def test_on_subagent_end_emits(self):
        ti = self._make_trace()
        ti.on_subagent_end("code-reviewer", "/tmp/trace.jsonl", True, 12.5)

        ti._emitter.emit.assert_called_once()
        args, kwargs = ti._emitter.emit.call_args
        assert args[0] == "agent"
        assert args[1] == "agent"
        assert args[3] == "subagent_end"
        assert kwargs["sections"]["success"] == "True"
        assert kwargs["sections"]["trace_path"] == "/tmp/trace.jsonl"

    def test_on_subagent_end_failure(self):
        ti = self._make_trace()
        ti.on_subagent_end("planner", "/tmp/trace.jsonl", False, 3.2)

        args, kwargs = ti._emitter.emit.call_args
        assert "[FAIL]" in kwargs["data"]
        assert kwargs["sections"]["success"] == "False"

    def test_on_subagent_start_with_iteration(self):
        ti = self._make_trace()
        ti.on_subagent_start("explore", "find utils", "/tmp/t.jsonl", iteration=2)

        args, _ = ti._emitter.emit.call_args
        assert "(iter 2)" in args[2]

    def test_on_subagent_start_truncates_long_task(self):
        ti = self._make_trace()
        long_task = "x" * 300
        ti.on_subagent_start("test", long_task, "/tmp/t.jsonl")

        _, kwargs = ti._emitter.emit.call_args
        assert len(kwargs["sections"]["task"]) <= 203  # 200 + "..."


class TestSubagentBookendNoOps:
    """Bookend methods are no-ops when disabled or no emitter."""

    def test_on_subagent_start_noop_when_disabled(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)
        ti.on_subagent_start("test", "task", "/tmp/t.jsonl")
        # No exception, no emitter call

    def test_on_subagent_end_noop_when_disabled(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)
        ti.on_subagent_end("test", "/tmp/t.jsonl", True, 1.0)

    def test_on_subagent_start_noop_when_no_emitter(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        # _emitter is None (no init_session called)
        ti.on_subagent_start("test", "task", "/tmp/t.jsonl")

    def test_on_subagent_start_handles_emitter_exception(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._emitter = MagicMock()
        ti._emitter.emit.side_effect = RuntimeError("boom")
        # Should not raise -- logs warning instead
        ti.on_subagent_start("test", "task", "/tmp/t.jsonl")

    def test_on_subagent_end_handles_emitter_exception(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._emitter = MagicMock()
        ti._emitter.emit.side_effect = RuntimeError("boom")
        ti.on_subagent_end("test", "/tmp/t.jsonl", True, 1.0)


# ---------------------------------------------------------------------------
# DelegateToSubagentTool.set_trace
# ---------------------------------------------------------------------------


class TestDelegationToolSetTrace:
    """DelegateToSubagentTool.set_trace wiring."""

    def test_set_trace_stores_reference(self):
        from src.tools.delegation import DelegateToSubagentTool

        mock_manager = MagicMock()
        mock_manager.get_available_subagents.return_value = ["code-reviewer"]
        mock_manager.configs = {}
        tool = DelegateToSubagentTool(mock_manager)

        mock_trace = MagicMock()
        tool.set_trace(mock_trace)
        assert tool._trace is mock_trace

    def test_set_trace_none_safe(self):
        from src.tools.delegation import DelegateToSubagentTool

        mock_manager = MagicMock()
        mock_manager.get_available_subagents.return_value = []
        mock_manager.configs = {}
        tool = DelegateToSubagentTool(mock_manager)
        tool.set_trace(None)
        assert tool._trace is None


# ---------------------------------------------------------------------------
# SubprocessInput.trace_enabled serialization
# ---------------------------------------------------------------------------


class TestSubprocessInputTraceEnabled:
    """trace_enabled field round-trips through JSON serialization."""

    def test_trace_enabled_default_false(self):
        from src.subagents.ipc import SubprocessInput

        inp = SubprocessInput(
            config={}, llm_config={}, api_key="test",
            task_description="test", working_directory="/tmp",
        )
        assert inp.trace_enabled is False

    def test_trace_enabled_set_true(self):
        from src.subagents.ipc import SubprocessInput

        inp = SubprocessInput(
            config={}, llm_config={}, api_key="test",
            task_description="test", working_directory="/tmp",
            trace_enabled=True,
        )
        assert inp.trace_enabled is True

    def test_trace_enabled_round_trips_through_json(self):
        from src.subagents.ipc import SubprocessInput

        inp = SubprocessInput(
            config={}, llm_config={}, api_key="test",
            task_description="test", working_directory="/tmp",
            trace_enabled=True,
        )
        json_str = inp.to_json()
        restored = SubprocessInput.from_json(json_str)
        assert restored.trace_enabled is True

    def test_trace_enabled_false_round_trips(self):
        from src.subagents.ipc import SubprocessInput

        inp = SubprocessInput(
            config={}, llm_config={}, api_key="test",
            task_description="test", working_directory="/tmp",
            trace_enabled=False,
        )
        json_str = inp.to_json()
        restored = SubprocessInput.from_json(json_str)
        assert restored.trace_enabled is False


# ---------------------------------------------------------------------------
# SubAgent trace instrumentation
# ---------------------------------------------------------------------------


class TestSubAgentTraceInstrumentation:
    """SubAgent fires trace events in correct order."""

    def _make_subagent(self, trace_enabled=True):
        """Create a SubAgent with mocked dependencies and optional trace."""
        from src.core.trace_integration import TraceIntegration
        from src.subagents.config import SubAgentConfig
        from src.subagents.subagent import SubAgent

        config = SubAgentConfig(
            name="test-sub",
            description="Test subagent",
            system_prompt="You are a test agent.",
        )

        mock_llm = MagicMock()
        mock_tool_executor = MagicMock()
        mock_tool_executor.tools = {}

        subagent = SubAgent(
            config=config,
            llm=mock_llm,
            tool_executor=mock_tool_executor,
            working_directory="/tmp",
        )

        if trace_enabled:
            trace = TraceIntegration(enabled=True)
            trace._emitter = MagicMock()
            subagent.set_trace(trace)

        return subagent

    def test_set_trace_replaces_default(self):
        subagent = self._make_subagent(trace_enabled=False)
        assert subagent._trace.enabled is False

        mock_trace = MagicMock()
        subagent.set_trace(mock_trace)
        assert subagent._trace is mock_trace

    def test_default_trace_is_disabled(self):
        subagent = self._make_subagent(trace_enabled=False)
        assert subagent._trace.enabled is False

    def test_on_request_called_during_execute(self):
        """on_request fires when execute() starts."""
        subagent = self._make_subagent()

        # Mock LLM to return a final response (no tool calls)
        mock_response = MagicMock()
        mock_response.content = "Done"
        mock_response.tool_calls = None
        mock_response.total_tokens = 100
        mock_response.prompt_tokens = 50
        subagent.llm.generate_with_tools.return_value = mock_response

        subagent.execute("Test task", max_iterations=5)

        # Check that on_request was called (first emit call)
        emit_calls = subagent._trace._emitter.emit.call_args_list
        assert len(emit_calls) >= 1
        first_call = emit_calls[0]
        assert first_call[0][0] == "user"  # from
        assert first_call[0][1] == "agent"  # to
        assert first_call[0][3] == "request"  # step_type

    def test_llm_call_and_response_traced(self):
        """on_llm_call and on_llm_response fire during execute."""
        subagent = self._make_subagent()

        mock_response = MagicMock()
        mock_response.content = "Final answer"
        mock_response.tool_calls = None
        mock_response.total_tokens = 100
        mock_response.prompt_tokens = 50
        subagent.llm.generate_with_tools.return_value = mock_response

        subagent.execute("Test task", max_iterations=5)

        emit_calls = subagent._trace._emitter.emit.call_args_list
        step_types = [c[0][3] for c in emit_calls]

        assert "request" in step_types
        assert "context_assembly" in step_types  # on_context_ready
        assert "llm_call" in step_types
        assert "llm_response" in step_types

    def test_response_sent_called_on_success(self):
        """on_response_sent fires at end of successful execute."""
        subagent = self._make_subagent()

        mock_response = MagicMock()
        mock_response.content = "Done"
        mock_response.tool_calls = None
        mock_response.total_tokens = 50
        mock_response.prompt_tokens = 25
        subagent.llm.generate_with_tools.return_value = mock_response

        result = subagent.execute("Test", max_iterations=5)
        assert result.success is True

        emit_calls = subagent._trace._emitter.emit.call_args_list
        last_call = emit_calls[-1]
        assert last_call[0][0] == "agent"  # from
        assert last_call[0][1] == "user"  # to
        assert last_call[0][3] == "request"  # on_response_sent uses "request" type

    def test_no_trace_calls_when_disabled(self):
        """Trace disabled = no emitter calls (safe no-ops)."""
        subagent = self._make_subagent(trace_enabled=False)

        mock_response = MagicMock()
        mock_response.content = "Done"
        mock_response.tool_calls = None
        mock_response.total_tokens = 50
        mock_response.prompt_tokens = 25
        subagent.llm.generate_with_tools.return_value = mock_response

        result = subagent.execute("Test", max_iterations=5)
        assert result.success is True
        # Default TraceIntegration has no emitter, so nothing called
