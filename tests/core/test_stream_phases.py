"""
Unit tests for stream_phases helper functions.

No API calls needed - all inputs are plain data.
"""

import json
import pytest
from unittest.mock import MagicMock

from src.core.stream_phases import (
    build_assistant_context_message,
    inject_controller_constraint,
    fill_skipped_tool_results,
    build_pause_stats,
)


# ---------------------------------------------------------------------------
# Helper: create mock ToolCall objects
# ---------------------------------------------------------------------------

def _make_tc(name="read_file", arguments='{"file_path": "/tmp/a.txt"}', call_id="call_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    tc.function.get_parsed_arguments.return_value = json.loads(arguments)
    return tc


# ---------------------------------------------------------------------------
# Test: build_assistant_context_message
# ---------------------------------------------------------------------------

class TestBuildAssistantContextMessage:

    def test_text_only(self):
        msg = build_assistant_context_message("Hello world")
        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello world"
        assert "tool_calls" not in msg

    def test_with_tool_calls(self):
        tc = _make_tc()
        msg = build_assistant_context_message("I'll read the file.", [tc])
        assert msg["role"] == "assistant"
        assert msg["content"] == "I'll read the file."
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "call_1"
        assert msg["tool_calls"][0]["type"] == "function"
        assert msg["tool_calls"][0]["function"]["name"] == "read_file"

    def test_empty_content_with_tool_calls(self):
        tc = _make_tc()
        msg = build_assistant_context_message("", [tc])
        assert msg["content"] == ""
        assert len(msg["tool_calls"]) == 1

    def test_multiple_tool_calls(self):
        tc1 = _make_tc(name="read_file", call_id="call_1")
        tc2 = _make_tc(name="grep", arguments='{"pattern": "foo"}', call_id="call_2")
        msg = build_assistant_context_message("Let me search.", [tc1, tc2])
        assert len(msg["tool_calls"]) == 2
        assert msg["tool_calls"][1]["function"]["name"] == "grep"


# ---------------------------------------------------------------------------
# Test: inject_controller_constraint
# ---------------------------------------------------------------------------

class TestInjectControllerConstraint:

    def test_no_blocked_calls_no_change(self):
        context = [{"role": "user", "content": "hi"}]
        inject_controller_constraint(context, [])
        assert len(context) == 1

    def test_blocked_calls_adds_constraint(self):
        context = [{"role": "user", "content": "hi"}]
        inject_controller_constraint(context, ["read_file(/tmp/x.txt)"])
        assert len(context) == 2
        assert context[-1]["role"] == "user"
        assert "BLOCKED" in context[-1]["content"]
        assert "read_file(/tmp/x.txt)" in context[-1]["content"]

    def test_multiple_blocked_calls(self):
        context = []
        inject_controller_constraint(context, ["call_a", "call_b"])
        assert "call_a" in context[-1]["content"]
        assert "call_b" in context[-1]["content"]


# ---------------------------------------------------------------------------
# Test: fill_skipped_tool_results
# ---------------------------------------------------------------------------

class TestFillSkippedToolResults:

    def test_all_processed_returns_empty(self):
        tc = _make_tc(call_id="call_1")
        result = fill_skipped_tool_results([tc], {"call_1"})
        assert result == []

    def test_unprocessed_gets_skipped_message(self):
        tc1 = _make_tc(name="read_file", call_id="call_1")
        tc2 = _make_tc(name="write_file", call_id="call_2")
        result = fill_skipped_tool_results([tc1, tc2], {"call_1"})
        assert len(result) == 1
        assert result[0]["tool_call_id"] == "call_2"
        assert result[0]["name"] == "write_file"
        assert "skipped" in result[0]["content"].lower()

    def test_custom_reason(self):
        tc = _make_tc(call_id="call_1")
        result = fill_skipped_tool_results([tc], set(), reason="Custom reason")
        assert result[0]["content"] == "Custom reason"


# ---------------------------------------------------------------------------
# Test: build_pause_stats
# ---------------------------------------------------------------------------

class TestBuildPauseStats:

    def test_basic_stats(self):
        stats = build_pause_stats(tool_call_count=5, elapsed_seconds=10.5, iteration=3)
        assert stats["tool_calls"] == 5
        assert stats["elapsed_s"] == 10.5
        assert stats["iterations"] == 3
        assert "error" not in stats

    def test_with_error(self):
        stats = build_pause_stats(5, 10.0, 3, error="Connection timeout")
        assert stats["error"] == "Connection timeout"
