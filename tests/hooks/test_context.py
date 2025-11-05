"""Unit tests for hook context classes."""

import pytest
from datetime import datetime
from src.hooks.context import (
    HookContext,
    PreToolUseContext,
    PostToolUseContext,
    UserPromptSubmitContext,
    NotificationContext,
    SessionStartContext,
    SessionEndContext,
    PreCompactContext,
    StopContext,
    SubagentStopContext,
)


class TestHookContext:
    """Test base HookContext class."""

    def test_create_minimal_context(self):
        """Test creating context with required fields only."""
        context = HookContext(
            session_id="test-session",
            event_type="TestEvent"
        )

        assert context.session_id == "test-session"
        assert context.event_type == "TestEvent"
        assert isinstance(context.timestamp, datetime)

    def test_context_timestamp_auto_generated(self):
        """Test that timestamp is auto-generated."""
        context = HookContext(
            session_id="test",
            event_type="Test"
        )

        assert context.timestamp is not None
        assert isinstance(context.timestamp, datetime)


class TestPreToolUseContext:
    """Test PreToolUseContext."""

    def test_create_minimal(self):
        """Test creating context with required fields."""
        context = PreToolUseContext(
            session_id="test",
            event_type="PreToolUse",
            tool="write_file"
        )

        assert context.tool == "write_file"
        assert context.arguments == {}
        assert context.step_id is None

    def test_create_with_arguments(self):
        """Test creating context with arguments."""
        context = PreToolUseContext(
            session_id="test",
            event_type="PreToolUse",
            tool="write_file",
            arguments={"file_path": "test.py", "content": "print('hello')"}
        )

        assert context.arguments["file_path"] == "test.py"
        assert context.arguments["content"] == "print('hello')"

    def test_create_with_step_id(self):
        """Test creating context with step_id."""
        context = PreToolUseContext(
            session_id="test",
            event_type="PreToolUse",
            tool="write_file",
            step_id=42
        )

        assert context.step_id == 42

    def test_arguments_mutable(self):
        """Test that arguments can be modified."""
        context = PreToolUseContext(
            session_id="test",
            event_type="PreToolUse",
            tool="write_file",
            arguments={"file_path": "test.py"}
        )

        context.arguments["validated"] = True
        assert context.arguments["validated"] is True


class TestPostToolUseContext:
    """Test PostToolUseContext."""

    def test_create_success_case(self):
        """Test creating context for successful tool execution."""
        context = PostToolUseContext(
            session_id="test",
            event_type="PostToolUse",
            tool="write_file",
            arguments={"file_path": "test.py"},
            result={"status": "success"},
            success=True,
            duration=0.5
        )

        assert context.success is True
        assert context.duration == 0.5
        assert context.error is None

    def test_create_failure_case(self):
        """Test creating context for failed tool execution."""
        context = PostToolUseContext(
            session_id="test",
            event_type="PostToolUse",
            tool="write_file",
            arguments={"file_path": "test.py"},
            result=None,
            success=False,
            duration=0.1,
            error="File not found"
        )

        assert context.success is False
        assert context.error == "File not found"


class TestUserPromptSubmitContext:
    """Test UserPromptSubmitContext."""

    def test_create_minimal(self):
        """Test creating with just prompt."""
        context = UserPromptSubmitContext(
            session_id="test",
            event_type="UserPromptSubmit",
            prompt="Write hello world"
        )

        assert context.prompt == "Write hello world"
        assert context.metadata == {}

    def test_create_with_metadata(self):
        """Test creating with metadata."""
        context = UserPromptSubmitContext(
            session_id="test",
            event_type="UserPromptSubmit",
            prompt="Test",
            metadata={"source": "cli", "user": "john"}
        )

        assert context.metadata["source"] == "cli"
        assert context.metadata["user"] == "john"


class TestNotificationContext:
    """Test NotificationContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = NotificationContext(
            session_id="test",
            event_type="Notification",
            notification_type="approval_request",
            message="Approve file write?"
        )

        assert context.notification_type == "approval_request"
        assert context.message == "Approve file write?"
        assert context.step_info is None
        assert context.risk_level is None

    def test_create_with_risk_level(self):
        """Test creating with risk level."""
        context = NotificationContext(
            session_id="test",
            event_type="Notification",
            notification_type="approval",
            message="Delete file?",
            risk_level="high"
        )

        assert context.risk_level == "high"

    def test_create_with_step_info(self):
        """Test creating with step info."""
        context = NotificationContext(
            session_id="test",
            event_type="Notification",
            notification_type="approval",
            message="Test",
            step_info={"step_id": 1, "tool": "delete_file"}
        )

        assert context.step_info["step_id"] == 1
        assert context.step_info["tool"] == "delete_file"


class TestSessionStartContext:
    """Test SessionStartContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = SessionStartContext(
            session_id="test",
            event_type="SessionStart",
            working_directory="/project",
            model_name="gpt-4"
        )

        assert context.working_directory == "/project"
        assert context.model_name == "gpt-4"
        assert context.config == {}

    def test_create_with_config(self):
        """Test creating with configuration."""
        context = SessionStartContext(
            session_id="test",
            event_type="SessionStart",
            working_directory="/project",
            model_name="gpt-4",
            config={"context_window": 32768, "temperature": 0.7}
        )

        assert context.config["context_window"] == 32768
        assert context.config["temperature"] == 0.7


class TestSessionEndContext:
    """Test SessionEndContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = SessionEndContext(
            session_id="test",
            event_type="SessionEnd",
            duration=300.5
        )

        assert context.duration == 300.5
        assert context.statistics == {}
        assert context.exit_reason == "normal"

    def test_create_with_statistics(self):
        """Test creating with statistics."""
        context = SessionEndContext(
            session_id="test",
            event_type="SessionEnd",
            duration=100.0,
            statistics={"tools_called": 42, "tokens_used": 1500}
        )

        assert context.statistics["tools_called"] == 42
        assert context.statistics["tokens_used"] == 1500

    def test_create_with_error_exit(self):
        """Test creating with error exit reason."""
        context = SessionEndContext(
            session_id="test",
            event_type="SessionEnd",
            duration=50.0,
            exit_reason="error"
        )

        assert context.exit_reason == "error"


class TestPreCompactContext:
    """Test PreCompactContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = PreCompactContext(
            session_id="test",
            event_type="PreCompact",
            current_tokens=40000,
            target_tokens=32000
        )

        assert context.current_tokens == 40000
        assert context.target_tokens == 32000
        assert context.messages_to_drop == []

    def test_create_with_messages(self):
        """Test creating with messages to drop."""
        context = PreCompactContext(
            session_id="test",
            event_type="PreCompact",
            current_tokens=40000,
            target_tokens=32000,
            messages_to_drop=["msg1", "msg2", "msg3"]
        )

        assert len(context.messages_to_drop) == 3
        assert "msg1" in context.messages_to_drop


class TestStopContext:
    """Test StopContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = StopContext(
            session_id="test",
            event_type="Stop",
            response="Task completed successfully",
            execution_time=5.5
        )

        assert context.response == "Task completed successfully"
        assert context.execution_time == 5.5
        assert context.tool_calls == []

    def test_create_with_tool_calls(self):
        """Test creating with tool calls."""
        context = StopContext(
            session_id="test",
            event_type="Stop",
            response="Done",
            execution_time=2.0,
            tool_calls=[
                {"tool": "write_file", "args": {"file_path": "test.py"}},
                {"tool": "read_file", "args": {"file_path": "test.py"}}
            ]
        )

        assert len(context.tool_calls) == 2
        assert context.tool_calls[0]["tool"] == "write_file"


class TestSubagentStopContext:
    """Test SubagentStopContext."""

    def test_create_minimal(self):
        """Test creating with required fields."""
        context = SubagentStopContext(
            session_id="test",
            event_type="SubagentStop",
            subagent_name="code-reviewer",
            result={"status": "complete"},
            duration=10.5
        )

        assert context.subagent_name == "code-reviewer"
        assert context.result["status"] == "complete"
        assert context.duration == 10.5


class TestContextSerialization:
    """Test that contexts can be serialized and deserialized."""

    def test_pre_tool_use_dict_conversion(self):
        """Test PreToolUseContext to dict conversion."""
        context = PreToolUseContext(
            session_id="test",
            event_type="PreToolUse",
            tool="write_file",
            arguments={"file_path": "test.py"}
        )

        # Convert to dict
        context_dict = context.model_dump()

        assert context_dict["session_id"] == "test"
        assert context_dict["tool"] == "write_file"
        assert context_dict["arguments"]["file_path"] == "test.py"

    def test_post_tool_use_dict_conversion(self):
        """Test PostToolUseContext to dict conversion."""
        context = PostToolUseContext(
            session_id="test",
            event_type="PostToolUse",
            tool="write_file",
            arguments={"file_path": "test.py"},
            result={"success": True},
            success=True,
            duration=0.5
        )

        context_dict = context.model_dump()

        assert context_dict["success"] is True
        assert context_dict["duration"] == 0.5

    def test_context_with_datetime_serialization(self):
        """Test that datetime fields serialize correctly."""
        context = HookContext(
            session_id="test",
            event_type="Test"
        )

        # Should be able to convert to dict with datetime
        context_dict = context.model_dump()
        assert "timestamp" in context_dict
        assert isinstance(context_dict["timestamp"], datetime)
