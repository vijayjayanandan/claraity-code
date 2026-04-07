"""
Test suite for trace integration and context builder trace wiring.

Coverage:
- TraceIntegration: State management, safe no-ops, event emission, iteration tags
- ContextBuilder: Trace source emission on first build, suppression on second build,
  set_trace(None) safety, source content accuracy

Total: 45+ tests covering TraceIntegration + ContextBuilder trace wiring
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest


# ---------------------------------------------------------------------------
# TraceIntegration tests
# ---------------------------------------------------------------------------


class TestTraceIntegrationStateManagement:
    """State management: is_first_build, mark_build_complete, init_session."""

    def test_is_first_build_starts_true(self):
        """is_first_build is True when no builds have occurred."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        assert ti.is_first_build is True

    def test_is_first_build_false_after_mark_build_complete(self):
        """is_first_build becomes False after mark_build_complete()."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        ti.mark_build_complete()
        assert ti.is_first_build is False

    def test_mark_build_complete_increments(self):
        """Multiple mark_build_complete calls keep is_first_build False."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        ti.mark_build_complete()
        ti.mark_build_complete()
        assert ti._context_build_n == 2
        assert ti.is_first_build is False

    def test_init_session_resets_context_build_n(self):
        """init_session resets _context_build_n so is_first_build becomes True again."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti.mark_build_complete()
        assert ti.is_first_build is False

        # init_session imports TraceEmitter locally, so patch at source module
        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            MockEmitter.return_value = MagicMock()
            ti.init_session("test-session", Path("/tmp/sessions"))

        assert ti._context_build_n == 0
        assert ti.is_first_build is True

    def test_init_session_resets_llm_call_n(self):
        """init_session resets _llm_call_n to 0."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._llm_call_n = 5

        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            MockEmitter.return_value = MagicMock()
            ti.init_session("test-session", Path("/tmp/sessions"))

        assert ti._llm_call_n == 0

    def test_init_session_sets_emitter(self):
        """init_session creates and stores a TraceEmitter."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        assert ti._emitter is None

        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            mock_emitter = MagicMock()
            MockEmitter.return_value = mock_emitter
            ti.init_session("sess-123", Path("/tmp/sessions"))

        assert ti._emitter is mock_emitter

    def test_init_session_failure_leaves_emitter_none(self):
        """If TraceEmitter constructor raises, emitter stays None (graceful degradation)."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        with patch(
            "src.observability.trace_emitter.TraceEmitter",
            side_effect=RuntimeError("init failed"),
        ):
            ti.init_session("sess-123", Path("/tmp/sessions"))

        assert ti._emitter is None


class TestTraceIntegrationSafeNoOps:
    """All on_* methods are safe no-ops when _emitter is None."""

    @pytest.fixture
    def uninitialised_trace(self):
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        assert ti._emitter is None
        return ti

    def test_on_request_noop(self, uninitialised_trace):
        uninitialised_trace.on_request("hello")

    def test_on_context_source_noop(self, uninitialised_trace):
        uninitialised_trace.on_context_source("Sys", "content", True)

    def test_on_context_store_fetch_noop(self, uninitialised_trace):
        uninitialised_trace.on_context_store_fetch(5, {"user": 3, "assistant": 2})

    def test_on_context_store_return_noop(self, uninitialised_trace):
        uninitialised_trace.on_context_store_return(5, 1000)

    def test_on_context_ready_noop(self, uninitialised_trace):
        uninitialised_trace.on_context_ready([{"role": "user", "content": "hi"}])

    def test_on_llm_call_noop(self, uninitialised_trace):
        uninitialised_trace.on_llm_call([{"role": "system", "content": "sys"}], None)

    def test_on_llm_response_noop(self, uninitialised_trace):
        uninitialised_trace.on_llm_response(None, "response text", None)

    def test_on_gate_check_noop(self, uninitialised_trace):
        uninitialised_trace.on_gate_check("edit_file", "ALLOW")

    def test_on_tools_dispatch_noop(self, uninitialised_trace):
        uninitialised_trace.on_tool_dispatch("edit_file", {})

    def test_on_tools_complete_noop(self, uninitialised_trace):
        uninitialised_trace.on_tools_complete([])

    def test_on_persist_noop(self, uninitialised_trace):
        uninitialised_trace.on_persist("sess-123")

    def test_on_response_sent_noop(self, uninitialised_trace):
        uninitialised_trace.on_response_sent()


# ---------------------------------------------------------------------------
# Helper: create a TraceIntegration with a mock emitter
# ---------------------------------------------------------------------------

def _make_trace_with_mock_emitter():
    """Return (TraceIntegration, mock_emitter) with emitter already set."""
    from src.core.trace_integration import TraceIntegration

    ti = TraceIntegration(enabled=True)
    mock_emitter = MagicMock()
    mock_emitter.format_tools = MagicMock(return_value="(tools list)")
    mock_emitter.format_messages = MagicMock(return_value="(messages list)")
    mock_emitter.format_tool_calls = MagicMock(return_value="(tool calls)")
    mock_emitter.format_tool_results = MagicMock(return_value="(tool results)")
    ti._emitter = mock_emitter
    return ti, mock_emitter


def _make_tool_call(name: str, args: dict | None = None):
    """Create a mock tool call object matching the ToolCall interface."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.get_parsed_arguments.return_value = args or {}
    return tc


class TestTraceIntegrationEventEmission:
    """Verify each on_* method emits the correct from/to/type."""

    def test_on_request_emits_user_to_agent(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_request("Hello agent")

        emitter.emit.assert_called_once()
        args, kwargs = emitter.emit.call_args
        assert args[0] == "user"       # from
        assert args[1] == "agent"      # to
        assert args[3] == "request"    # type
        assert kwargs["data"] == "Hello agent"

    def test_on_context_source_emits_self_referencing(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_source("System Prompt", "prompt content", True)

        emitter.emit.assert_called_once()
        args, kwargs = emitter.emit.call_args
        assert args[0] == "context_builder"
        assert args[1] == "context_builder"
        assert args[3] == "context_source"
        assert "loaded" in args[2]

    def test_on_context_source_not_found(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_source("CLARAITY.md", "", False)

        args, kwargs = emitter.emit.call_args
        assert "not found" in args[2]
        assert kwargs["data"] == "(CLARAITY.md not available)"

    def test_on_context_store_fetch_emits_to_store(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_store_fetch(10, {"user": 5, "assistant": 5})

        args, kwargs = emitter.emit.call_args
        assert args[0] == "context_builder"
        assert args[1] == "store"
        assert args[3] == "context_source"
        assert "10 msgs" in args[2]

    def test_on_context_store_return_emits_from_store(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_store_return(10, 5000)

        args, kwargs = emitter.emit.call_args
        assert args[0] == "store"
        assert args[1] == "context_builder"
        assert args[3] == "context_source"
        assert "10 messages" in args[2]

    def test_on_context_ready_emits_agent_to_context_builder(self):
        ti, emitter = _make_trace_with_mock_emitter()
        context = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        ti.on_context_ready(context)

        args, kwargs = emitter.emit.call_args
        assert args[0] == "agent"
        assert args[1] == "context_builder"
        assert args[3] == "context_assembly"
        assert "2 msgs" in args[2]

    def test_on_llm_call_emits_context_builder_to_llm(self):
        ti, emitter = _make_trace_with_mock_emitter()
        context = [{"role": "system", "content": "You are helpful."}]
        tools = [{"function": {"name": "read_file"}}]

        ti.on_llm_call(context, tools)

        args, kwargs = emitter.emit.call_args
        assert args[0] == "context_builder"
        assert args[1] == "llm"
        assert args[3] == "llm_call"

    def test_on_llm_call_increments_llm_call_n(self):
        ti, emitter = _make_trace_with_mock_emitter()
        context = [{"role": "system", "content": "sys"}]

        assert ti._llm_call_n == 0
        ti.on_llm_call(context, None)
        assert ti._llm_call_n == 1
        ti.on_llm_call(context, None)
        assert ti._llm_call_n == 2

    def test_on_llm_call_sections_include_system_tools_messages(self):
        ti, emitter = _make_trace_with_mock_emitter()
        context = [{"role": "system", "content": "You are helpful."}]

        ti.on_llm_call(context, [{"function": {"name": "read"}}])

        _, kwargs = emitter.emit.call_args
        sections = kwargs["sections"]
        assert "System Prompt" in sections
        assert sections["System Prompt"] == "You are helpful."
        assert "Tools" in sections
        assert "Messages" in sections

    def test_on_llm_call_extracts_system_prompt_from_context(self):
        """System prompt is extracted from the first system message."""
        ti, emitter = _make_trace_with_mock_emitter()
        context = [
            {"role": "system", "content": "First system msg"},
            {"role": "system", "content": "Second system msg"},
            {"role": "user", "content": "Hello"},
        ]

        ti.on_llm_call(context, None)

        _, kwargs = emitter.emit.call_args
        assert kwargs["sections"]["System Prompt"] == "First system msg"

    def test_on_llm_response_emits_llm_to_agent(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_llm_response(None, "Here is the answer", None)

        args, kwargs = emitter.emit.call_args
        assert args[0] == "llm"
        assert args[1] == "agent"
        assert args[3] == "llm_response"
        assert "Final text response" in args[2]

    def test_on_llm_response_with_tool_calls(self):
        ti, emitter = _make_trace_with_mock_emitter()
        tc = _make_tool_call("read_file")

        ti.on_llm_response([tc], "", None)

        args, kwargs = emitter.emit.call_args
        assert "read_file" in args[2]

    def test_on_llm_response_includes_thinking_section(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_llm_response(None, "answer", "I need to think about this")

        _, kwargs = emitter.emit.call_args
        assert kwargs["sections"]["Thinking"] == "I need to think about this"
        assert kwargs["thinking"] == "I need to think about this"

    def test_on_gate_check_emits_agent_to_gating(self):
        ti, emitter = _make_trace_with_mock_emitter()

        ti.on_gate_check("write_file", "ALLOW")

        args, kwargs = emitter.emit.call_args
        assert args[0] == "agent"
        assert args[1] == "gating"
        assert args[3] == "gate_check"
        assert "write_file" in args[2]
        assert "ALLOW" in args[2]

    def test_on_tool_dispatch_emits_gating_to_tools(self):
        ti, emitter = _make_trace_with_mock_emitter()

        ti.on_tool_dispatch("edit_file", {"path": "/foo.py"})

        args, kwargs = emitter.emit.call_args
        assert args[0] == "gating"
        assert args[1] == "tools"
        assert args[3] == "tool_execute"
        assert "edit_file" in args[2]

    def test_on_tools_complete_emits_tools_to_agent(self):
        ti, emitter = _make_trace_with_mock_emitter()
        tool_msgs = [
            {"name": "read_file", "content": "file contents here"},
        ]

        ti.on_tools_complete(tool_msgs)

        args, kwargs = emitter.emit.call_args
        assert args[0] == "tools"
        assert args[1] == "agent"
        assert args[3] == "tool_result"
        assert "read_file" in args[2]

    def test_on_persist_emits_agent_to_store(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_persist("session-abc")

        args, kwargs = emitter.emit.call_args
        assert args[0] == "agent"
        assert args[1] == "store"
        assert args[3] == "persist"
        assert "session-abc" in kwargs["data"]

    def test_on_persist_with_none_session_id(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_persist(None)

        _, kwargs = emitter.emit.call_args
        assert "?" in kwargs["data"]

    def test_on_response_sent_emits_agent_to_user(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_response_sent()

        args, kwargs = emitter.emit.call_args
        assert args[0] == "agent"
        assert args[1] == "user"
        assert args[3] == "request"


class TestTraceIntegrationIterationTags:
    """Iteration > 0 includes '(iter N)' in labels; iteration == 0 does not."""

    def test_context_source_no_iter_tag_at_zero(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_source("System Prompt", "content", True, iteration=0)

        args, _ = emitter.emit.call_args
        label = args[2]
        assert "(iter" not in label

    def test_context_source_iter_tag_at_nonzero(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_source("System Prompt", "content", True, iteration=3)

        args, _ = emitter.emit.call_args
        label = args[2]
        assert "(iter 3)" in label

    def test_context_store_fetch_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_store_fetch(5, {"user": 3}, iteration=2)

        args, _ = emitter.emit.call_args
        assert "(iter 2)" in args[2]

    def test_context_store_return_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_store_return(5, 1000, iteration=1)

        args, _ = emitter.emit.call_args
        assert "(iter 1)" in args[2]

    def test_context_ready_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_context_ready([{"role": "user", "content": "hi"}], iteration=4)

        args, _ = emitter.emit.call_args
        assert "(iter 4)" in args[2]

    def test_llm_call_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_llm_call([{"role": "system", "content": "s"}], None, iteration=2)

        args, _ = emitter.emit.call_args
        assert "(iter 2)" in args[2]

    def test_gate_check_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_gate_check("read_file", "ALLOW", iteration=5)

        args, _ = emitter.emit.call_args
        assert "(iter 5)" in args[2]

    def test_tool_dispatch_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_tool_dispatch("read_file", {}, iteration=1)

        args, _ = emitter.emit.call_args
        assert "(iter 1)" in args[2]

    def test_tools_complete_iter_tag(self):
        ti, emitter = _make_trace_with_mock_emitter()
        ti.on_tools_complete(
            [{"name": "read_file", "content": "ok"}], iteration=3,
        )

        args, _ = emitter.emit.call_args
        assert "(iter 3)" in args[2]


class TestTraceIntegrationExceptionSafety:
    """on_* methods catch exceptions from the emitter and log warnings."""

    def test_on_request_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        # Should not raise
        ti.on_request("hello")

    def test_on_llm_call_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        ti.on_llm_call([{"role": "system", "content": "s"}], None)

    def test_on_llm_response_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        ti.on_llm_response(None, "text", None)

    def test_on_gate_check_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        ti.on_gate_check("x", "ALLOW")

    def test_on_tool_dispatch_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        ti.on_tool_dispatch("x", {})

    def test_on_tools_complete_catches_emitter_exception(self):
        ti, emitter = _make_trace_with_mock_emitter()
        emitter.emit.side_effect = RuntimeError("boom")
        ti.on_tools_complete([{"name": "x", "content": "ok"}])


# ---------------------------------------------------------------------------
# ContextBuilder trace wiring tests
# ---------------------------------------------------------------------------


class TestContextBuilderTraceWiring:
    """Verify ContextBuilder.build_context() emits trace events correctly."""

    @pytest.fixture
    def mock_memory(self):
        """Minimal mock MemoryManager for ContextBuilder."""
        mm = MagicMock()
        mm.get_context_for_llm.return_value = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        mm.file_memory_content = "memory file content here"
        mm.persistent_memory_content = ""
        mm.persistent_memory_dir = "/tmp/test/.claraity/memory"
        return mm

    @pytest.fixture
    def builder(self, mock_memory, tmp_path):
        """ContextBuilder with a mock MemoryManager and temp project root."""
        from src.core.context_builder import ContextBuilder

        cb = ContextBuilder(
            memory_manager=mock_memory,
            max_context_tokens=100000,
            reserved_output_tokens=1000,
            safety_buffer_tokens=500,
            tools_schema_tokens=500,
            project_root=tmp_path,
        )
        return cb

    @pytest.fixture
    def mock_trace(self):
        """Mock TraceIntegration that reports is_first_build=True, _ok=True."""
        trace = MagicMock()
        trace._ok = True
        trace.is_first_build = True
        return trace

    @pytest.fixture
    def mock_trace_second_build(self):
        """Mock TraceIntegration that reports is_first_build=False."""
        trace = MagicMock()
        trace._ok = True
        trace.is_first_build = False
        return trace

    def test_first_build_emits_context_sources(self, builder, mock_trace):
        """First build_context emits on_context_source for System Prompt,
        CLARAITY.md, Knowledge DB, Memory Files, and Persistent Memory."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        source_calls = mock_trace.on_context_source.call_args_list
        source_names = [c[0][0] for c in source_calls]
        assert "System Prompt" in source_names
        assert "CLARAITY.md" in source_names
        assert "Knowledge DB" in source_names
        assert "Memory Files" in source_names
        assert "Persistent Memory" in source_names
        assert len(source_names) == 5

    def test_first_build_emits_store_fetch(self, builder, mock_trace):
        """First build_context emits on_context_store_fetch."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        mock_trace.on_context_store_fetch.assert_called_once()
        args, _ = mock_trace.on_context_store_fetch.call_args
        assert args[0] == 2  # msg_count from mock_memory

    def test_first_build_emits_store_return(self, builder, mock_trace):
        """First build_context emits on_context_store_return."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        mock_trace.on_context_store_return.assert_called_once()
        args, _ = mock_trace.on_context_store_return.call_args
        assert args[0] == 2  # msg_count

    def test_first_build_calls_mark_build_complete(self, builder, mock_trace):
        """First build_context calls mark_build_complete() on the trace."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        mock_trace.mark_build_complete.assert_called_once()

    def test_second_build_does_not_emit_source_events(
        self, builder, mock_trace_second_build,
    ):
        """When is_first_build is False, no on_context_source calls are made."""
        builder.set_trace(mock_trace_second_build)
        builder.build_context(user_query="test", log_report=False)

        mock_trace_second_build.on_context_source.assert_not_called()
        mock_trace_second_build.on_context_store_fetch.assert_not_called()
        mock_trace_second_build.on_context_store_return.assert_not_called()
        mock_trace_second_build.mark_build_complete.assert_not_called()

    def test_set_trace_none_is_safe(self, builder):
        """set_trace(None) then build_context() does not crash."""
        builder.set_trace(None)
        result = builder.build_context(user_query="test", log_report=False)
        # Should return valid context without errors
        assert isinstance(result, list)
        assert len(result) > 0

    def test_claraity_md_found_passes_content(self, builder, mock_trace, tmp_path):
        """When CLARAITY.md exists, content is passed with found=True."""
        claraity_md = tmp_path / "CLARAITY.md"
        claraity_md.write_text("# Project Instructions\nDo the thing.", encoding="utf-8")

        # Reload cached sources since file was created after builder init
        builder.reload_cached_sources()
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        # Find the CLARAITY.md source call
        for c in mock_trace.on_context_source.call_args_list:
            if c[0][0] == "CLARAITY.md":
                content = c[0][1]
                found = c[0][2]
                assert found is True
                assert "Project Instructions" in content
                return
        pytest.fail("No on_context_source call for CLARAITY.md")

    def test_claraity_md_not_found_passes_not_found(self, builder, mock_trace):
        """When CLARAITY.md does not exist, (not found) is passed with found=False."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        for c in mock_trace.on_context_source.call_args_list:
            if c[0][0] == "CLARAITY.md":
                content = c[0][1]
                found = c[0][2]
                assert found is False
                assert content == "(not found)"
                return
        pytest.fail("No on_context_source call for CLARAITY.md")

    def test_memory_files_content_from_memory_manager(self, builder, mock_trace):
        """Memory Files source content comes from memory.file_memory_content."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        for c in mock_trace.on_context_source.call_args_list:
            if c[0][0] == "Memory Files":
                content = c[0][1]
                found = c[0][2]
                assert found is True
                assert content == "memory file content here"
                return
        pytest.fail("No on_context_source call for Memory Files")

    def test_memory_files_empty_when_no_content(self, builder, mock_trace, mock_memory):
        """When file_memory_content is empty, Memory Files reports not found."""
        mock_memory.file_memory_content = ""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        for c in mock_trace.on_context_source.call_args_list:
            if c[0][0] == "Memory Files":
                content = c[0][1]
                found = c[0][2]
                assert found is False
                assert content == "(no memory files loaded)"
                return
        pytest.fail("No on_context_source call for Memory Files")

    def test_store_fetch_role_breakdown(self, builder, mock_trace):
        """on_context_store_fetch receives correct role counts."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        args, _ = mock_trace.on_context_store_fetch.call_args
        roles = args[1]
        assert roles["user"] == 1
        assert roles["assistant"] == 1

    def test_iteration_passed_to_trace_events(self, builder, mock_trace):
        """iteration parameter is forwarded to trace source events."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False, iteration=5)

        # Check iteration passed to on_context_source
        for c in mock_trace.on_context_source.call_args_list:
            assert c[0][3] == 5  # iteration arg

        # Check iteration passed to store events
        _, kwargs_or_args = mock_trace.on_context_store_fetch.call_args
        assert mock_trace.on_context_store_fetch.call_args[0][2] == 5

    def test_system_prompt_source_always_found(self, builder, mock_trace):
        """System Prompt source is always emitted as found=True."""
        builder.set_trace(mock_trace)
        builder.build_context(user_query="test", log_report=False)

        for c in mock_trace.on_context_source.call_args_list:
            if c[0][0] == "System Prompt":
                assert c[0][2] is True  # found
                assert len(c[0][1]) > 0  # content is non-empty
                return
        pytest.fail("No on_context_source call for System Prompt")

    def test_build_context_without_trace_set(self, builder):
        """build_context works fine when no trace has been set at all."""
        # _trace defaults to None from __init__
        result = builder.build_context(user_query="test", log_report=False)
        assert isinstance(result, list)

    def test_trace_with_ok_false_skips_source_events(self, builder):
        """If trace._ok is False, source events are not emitted."""
        trace = MagicMock()
        trace._ok = False
        trace.is_first_build = True

        builder.set_trace(trace)
        builder.build_context(user_query="test", log_report=False)

        trace.on_context_source.assert_not_called()
        trace.on_context_store_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Approval flow tests
# ---------------------------------------------------------------------------


class TestTraceIntegrationApproval:
    """Approval request/result events."""

    @pytest.fixture
    def trace(self):
        from src.core.trace_integration import TraceIntegration
        t = TraceIntegration(enabled=True)
        t._emitter = MagicMock()
        return t

    def test_approval_request_emits_gating_to_user(self, trace):
        trace.on_approval_request("edit_file", {"path": "test.py"}, None, iteration=2)
        trace._emitter.emit.assert_called_once()
        args = trace._emitter.emit.call_args
        assert args[0][0] == "gating"
        assert args[0][1] == "user"
        assert args[0][3] == "approval"
        assert "edit_file" in args[0][2]
        assert "(iter 2)" in args[0][2]

    def test_approval_request_includes_safety_reason(self, trace):
        trace.on_approval_request("rm_file", {}, "destructive command", iteration=1)
        args = trace._emitter.emit.call_args
        assert "destructive command" in args[1]["data"]
        assert args[1]["sections"]["Reason"] == "destructive command"

    def test_approval_request_default_reason_when_none(self, trace):
        trace.on_approval_request("edit_file", {}, None)
        args = trace._emitter.emit.call_args
        assert "Category-based approval required" in args[1]["data"]

    def test_approval_request_truncates_long_args(self, trace):
        long_args = {"content": "x" * 500}
        trace.on_approval_request("write_file", long_args, None)
        args = trace._emitter.emit.call_args
        assert len(args[1]["sections"]["Arguments"]) <= 410  # 400 + "..."

    def test_approval_result_approved(self, trace):
        trace._approval_t0 = 0  # ensure attribute exists
        trace.on_approval_result("edit_file", True, None, iteration=2)
        args = trace._emitter.emit.call_args
        assert args[0][0] == "user"
        assert args[0][1] == "gating"
        assert args[0][3] == "approval"
        assert "approved" in args[0][2]
        assert "APPROVED" in args[1]["data"]

    def test_approval_result_rejected_no_feedback(self, trace):
        trace._approval_t0 = 0
        trace.on_approval_result("edit_file", False, None)
        args = trace._emitter.emit.call_args
        assert "rejected" in args[0][2]
        assert "Turn will end" in args[1]["data"]

    def test_approval_result_rejected_with_feedback(self, trace):
        trace._approval_t0 = 0
        trace.on_approval_result("edit_file", False, "use write_file instead")
        args = trace._emitter.emit.call_args
        assert "rejected" in args[0][2]
        assert "use write_file instead" in args[1]["data"]
        assert "loop continues" in args[1]["data"]

    def test_approval_request_noop_when_uninit(self):
        from src.core.trace_integration import TraceIntegration
        t = TraceIntegration()
        t.on_approval_request("test", {}, None)  # should not raise

    def test_approval_result_noop_when_uninit(self):
        from src.core.trace_integration import TraceIntegration
        t = TraceIntegration()
        t.on_approval_result("test", True, None)  # should not raise

    def test_approval_request_catches_exception(self, trace):
        trace._emitter.emit.side_effect = RuntimeError("boom")
        trace.on_approval_request("test", {}, None)  # should not raise


# ---------------------------------------------------------------------------
# Store write tests
# ---------------------------------------------------------------------------


class TestTraceIntegrationStoreWrite:
    """Store write events."""

    @pytest.fixture
    def trace(self):
        from src.core.trace_integration import TraceIntegration
        t = TraceIntegration(enabled=True)
        t._emitter = MagicMock()
        return t

    def test_store_write_emits_agent_to_store(self, trace):
        trace.on_store_write("user_message", "Saved user message")
        args = trace._emitter.emit.call_args
        assert args[0][0] == "agent"
        assert args[0][1] == "store"
        assert args[0][3] == "persist"
        assert "user_message" in args[0][2]

    def test_store_write_includes_iteration(self, trace):
        trace.on_store_write("tool_results", "Saved 2 results", iteration=3)
        args = trace._emitter.emit.call_args
        assert "(iter 3)" in args[0][2]

    def test_store_write_no_iter_tag_at_zero(self, trace):
        trace.on_store_write("assistant_message", "Saved response", iteration=0)
        args = trace._emitter.emit.call_args
        assert "(iter" not in args[0][2]

    def test_store_write_noop_when_uninit(self):
        from src.core.trace_integration import TraceIntegration
        t = TraceIntegration()
        t.on_store_write("test", "test")  # should not raise

    def test_store_write_catches_exception(self, trace):
        trace._emitter.emit.side_effect = RuntimeError("boom")
        trace.on_store_write("test", "test")  # should not raise


# ---------------------------------------------------------------------------
# Enabled flag tests
# ---------------------------------------------------------------------------


class TestTraceIntegrationEnabledFlag:
    """Tests for the enabled flag controlling trace capture."""

    def test_default_disabled(self):
        """TraceIntegration() has enabled=False by default."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration()
        assert ti.enabled is False

    def test_explicit_enabled(self):
        """TraceIntegration(enabled=True) has enabled=True."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        assert ti.enabled is True

    def test_ok_false_when_disabled(self):
        """Even with _emitter set, _ok returns False when disabled."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)
        ti._emitter = MagicMock()  # Emitter is set but disabled
        assert ti._ok is False

    def test_ok_true_when_enabled_and_emitter_set(self):
        """_ok returns True when both enabled and emitter set."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._emitter = MagicMock()
        assert ti._ok is True

    def test_set_enabled_true(self):
        """set_enabled(True) sets _enabled=True."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)
        assert ti.enabled is False

        ti.set_enabled(True)
        assert ti._enabled is True

    def test_set_enabled_false_drops_emitter(self):
        """set_enabled(False) sets _enabled=False AND sets _emitter=None."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)
        ti._emitter = MagicMock()

        ti.set_enabled(False)
        assert ti._enabled is False
        assert ti._emitter is None

    def test_init_session_skipped_when_disabled(self):
        """init_session() with enabled=False does NOT create emitter (stays None)."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)

        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            MockEmitter.return_value = MagicMock()
            ti.init_session("test-session", Path("/tmp/sessions"))

        assert ti._emitter is None
        MockEmitter.assert_not_called()

    def test_init_session_works_when_enabled(self):
        """init_session() with enabled=True creates emitter."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=True)

        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            mock_emitter = MagicMock()
            MockEmitter.return_value = mock_emitter
            ti.init_session("test-session", Path("/tmp/sessions"))

        assert ti._emitter is mock_emitter
        MockEmitter.assert_called_once_with("test-session", Path("/tmp/sessions"))

    def test_enable_mid_session_allows_future_init(self):
        """Create with enabled=False, call set_enabled(True), then init_session creates emitter."""
        from src.core.trace_integration import TraceIntegration

        ti = TraceIntegration(enabled=False)
        assert ti._emitter is None

        ti.set_enabled(True)

        with patch("src.observability.trace_emitter.TraceEmitter") as MockEmitter:
            mock_emitter = MagicMock()
            MockEmitter.return_value = mock_emitter
            ti.init_session("mid-session", Path("/tmp/sessions"))

        assert ti._emitter is mock_emitter
