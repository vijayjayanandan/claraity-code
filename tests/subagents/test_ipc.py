"""Tests for IPC protocol serialization and deserialization.

Verifies that StoreNotification, SubAgentResult, and SubprocessInput
survive JSON roundtrips through the IPC serialization layer.
"""

import json
import pytest

# Prime import chain (see conftest.py)
import src.core  # noqa: F401

from src.subagents.ipc import (
    SubprocessInput,
    IPCEventType,
    serialize_notification,
    deserialize_notification,
    serialize_result,
    deserialize_result,
    emit_event,
)
from src.session.store.memory_store import (
    StoreNotification, StoreEvent, ToolExecutionState,
)
from src.session.models.message import Message
from src.core.events import ToolStatus
from src.subagents.subagent import SubAgentResult


# ============================================================================
# SubprocessInput roundtrip
# ============================================================================

class TestSubprocessInput:
    """Tests for SubprocessInput serialization."""

    def test_roundtrip(self):
        """SubprocessInput survives JSON roundtrip."""
        inp = SubprocessInput(
            config={"name": "code-reviewer", "description": "Reviews code", "system_prompt": "You review code."},
            llm_config={"backend_type": "openai", "model_name": "gpt-4o", "base_url": "https://api.openai.com/v1",
                        "temperature": 0.7, "max_tokens": 4096, "top_p": 1.0, "context_window": 128000},
            api_key="sk-test-key",
            task_description="Review src/auth.py for security issues",
            working_directory="/home/user/project",
            max_iterations=25,
            transcript_path=".claraity/sessions/subagents/code-reviewer-abc123.jsonl",
        )

        json_str = inp.to_json()
        restored = SubprocessInput.from_json(json_str)

        assert restored.config["name"] == "code-reviewer"
        assert restored.llm_config["model_name"] == "gpt-4o"
        assert restored.api_key == "sk-test-key"
        assert restored.task_description == "Review src/auth.py for security issues"
        assert restored.working_directory == "/home/user/project"
        assert restored.max_iterations == 25
        assert restored.transcript_path == ".claraity/sessions/subagents/code-reviewer-abc123.jsonl"

    def test_defaults(self):
        """SubprocessInput uses correct defaults."""
        inp = SubprocessInput(
            config={},
            llm_config={},
            api_key="",
            task_description="test",
            working_directory=".",
        )
        assert inp.max_iterations == 50
        assert inp.transcript_path == ""


# ============================================================================
# StoreNotification roundtrip
# ============================================================================

class TestNotificationSerialization:
    """Tests for StoreNotification serialization/deserialization."""

    def test_message_added_roundtrip(self):
        """MESSAGE_ADDED notification with Message survives roundtrip."""
        msg = Message.create_user(
            content="Hello world",
            session_id="test-session",
            parent_uuid=None,
            seq=1,
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.event == StoreEvent.MESSAGE_ADDED
        assert restored.message is not None
        assert restored.message.role == "user"
        assert restored.message.content == "Hello world"

    def test_tool_state_roundtrip(self):
        """TOOL_STATE_UPDATED notification with ToolExecutionState survives roundtrip."""
        tool_state = ToolExecutionState(
            status=ToolStatus.RUNNING,
            result=None,
            error=None,
            duration_ms=None,
        )
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_abc123",
            tool_state=tool_state,
            metadata={"tool_name": "read_file", "args_summary": 'file_path="test.py"'},
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.event == StoreEvent.TOOL_STATE_UPDATED
        assert restored.tool_call_id == "call_abc123"
        assert restored.tool_state is not None
        assert restored.tool_state.status == ToolStatus.RUNNING
        assert restored.metadata["tool_name"] == "read_file"

    def test_tool_state_success_roundtrip(self):
        """Tool state with SUCCESS status and result survives roundtrip."""
        tool_state = ToolExecutionState(
            status=ToolStatus.SUCCESS,
            result="File contents here",
            error=None,
            duration_ms=150,
        )
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_xyz",
            tool_state=tool_state,
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.tool_state.status == ToolStatus.SUCCESS
        assert restored.tool_state.result == "File contents here"
        assert restored.tool_state.duration_ms == 150

    def test_tool_state_error_roundtrip(self):
        """Tool state with ERROR status survives roundtrip."""
        tool_state = ToolExecutionState(
            status=ToolStatus.ERROR,
            result=None,
            error="File not found",
            duration_ms=5,
        )
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_err",
            tool_state=tool_state,
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.tool_state.status == ToolStatus.ERROR
        assert restored.tool_state.error == "File not found"

    def test_assistant_message_with_tool_calls(self):
        """Assistant message with tool_calls survives roundtrip."""
        from src.session.models.message import ToolCall, ToolCallFunction

        tool_calls = [
            ToolCall(
                id="call_001",
                function=ToolCallFunction(
                    name="read_file",
                    arguments='{"file_path": "test.py"}',
                ),
            )
        ]
        msg = Message.create_assistant(
            content="Let me read that file.",
            session_id="test",
            parent_uuid=None,
            seq=2,
            tool_calls=tool_calls,
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.message.role == "assistant"
        assert len(restored.message.tool_calls) == 1
        assert restored.message.tool_calls[0].id == "call_001"
        assert restored.message.tool_calls[0].function.name == "read_file"

    def test_minimal_notification(self):
        """Notification with only event (no message/tool_state) survives roundtrip."""
        notification = StoreNotification(
            event=StoreEvent.STORE_CLEARED,
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.event == StoreEvent.STORE_CLEARED
        assert restored.message is None
        assert restored.tool_state is None

    def test_bulk_load_complete(self):
        """BULK_LOAD_COMPLETE notification survives roundtrip."""
        notification = StoreNotification(
            event=StoreEvent.BULK_LOAD_COMPLETE,
            metadata={"message_count": 42},
        )

        serialized = serialize_notification(notification)
        restored = deserialize_notification(serialized)

        assert restored.event == StoreEvent.BULK_LOAD_COMPLETE
        assert restored.metadata["message_count"] == 42


# ============================================================================
# SubAgentResult roundtrip
# ============================================================================

class TestResultSerialization:
    """Tests for SubAgentResult serialization/deserialization."""

    def test_success_result_roundtrip(self):
        """Successful SubAgentResult survives roundtrip."""
        result = SubAgentResult(
            success=True,
            subagent_name="code-reviewer",
            output="No issues found. Code looks clean.",
            metadata={
                "task_description": "Review auth.py",
                "model": "gpt-4o",
                "iterations": 3,
            },
            tool_calls=[
                {"tool": "read_file", "success": True, "result": "..."},
                {"tool": "search_code", "success": True, "result": "..."},
            ],
            execution_time=12.5,
        )

        serialized = serialize_result(result)
        restored = deserialize_result(serialized)

        assert restored.success is True
        assert restored.subagent_name == "code-reviewer"
        assert restored.output == "No issues found. Code looks clean."
        assert restored.metadata["model"] == "gpt-4o"
        assert len(restored.tool_calls) == 2
        assert restored.execution_time == 12.5
        assert restored.error is None

    def test_failure_result_roundtrip(self):
        """Failed SubAgentResult survives roundtrip."""
        result = SubAgentResult(
            success=False,
            subagent_name="test-writer",
            output="",
            error="API rate limit exceeded",
            execution_time=2.1,
        )

        serialized = serialize_result(result)
        restored = deserialize_result(serialized)

        assert restored.success is False
        assert restored.subagent_name == "test-writer"
        assert restored.output == ""
        assert restored.error == "API rate limit exceeded"
        assert restored.execution_time == 2.1

    def test_cancelled_result_roundtrip(self):
        """Cancelled SubAgentResult survives roundtrip."""
        result = SubAgentResult(
            success=False,
            subagent_name="doc-writer",
            output="",
            metadata={"cancelled": True},
            error="Cancelled by user",
            execution_time=5.0,
        )

        serialized = serialize_result(result)
        restored = deserialize_result(serialized)

        assert restored.success is False
        assert restored.metadata.get("cancelled") is True
        assert restored.error == "Cancelled by user"


# ============================================================================
# IPCEventType
# ============================================================================

class TestIPCEventType:
    """Tests for IPCEventType enum."""

    def test_event_type_values(self):
        """Event types have expected string values."""
        assert IPCEventType.REGISTERED == "registered"
        assert IPCEventType.NOTIFICATION == "notification"
        assert IPCEventType.DONE == "done"
        assert IPCEventType.ERROR == "error"

    def test_event_type_json_serialization(self):
        """Event types serialize to their string values in JSON."""
        event = {"type": IPCEventType.DONE.value, "result": {"success": True}}
        json_str = json.dumps(event)
        restored = json.loads(json_str)
        assert restored["type"] == "done"


# ============================================================================
# emit_event (stdout capture)
# ============================================================================

class TestEmitEvent:
    """Tests for emit_event function."""

    def test_emit_event_writes_json_line(self, capsys):
        """emit_event writes a valid JSON line to stdout."""
        emit_event(IPCEventType.REGISTERED, subagent_id="abc123", model_name="gpt-4o")

        captured = capsys.readouterr()
        line = captured.out.strip()
        event = json.loads(line)

        assert event["type"] == "registered"
        assert event["subagent_id"] == "abc123"
        assert event["model_name"] == "gpt-4o"

    def test_emit_event_done(self, capsys):
        """emit_event for DONE includes result data."""
        emit_event(
            IPCEventType.DONE,
            result={"success": True, "output": "All good"},
        )

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())

        assert event["type"] == "done"
        assert event["result"]["success"] is True

    def test_emit_event_error(self, capsys):
        """emit_event for ERROR includes error message."""
        emit_event(IPCEventType.ERROR, error="Something went wrong")

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())

        assert event["type"] == "error"
        assert event["error"] == "Something went wrong"
