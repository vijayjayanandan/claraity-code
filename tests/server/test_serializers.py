"""Unit tests for the VS Code server serializers.

Tests every UIEvent type serializes correctly, every UserAction
deserializes correctly, and edge cases are handled gracefully.
"""

import pytest
from src.core.events import (
    StreamStart, StreamEnd,
    TextDelta,
    CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    PausePromptStart, PausePromptEnd,
    ContextUpdated, ContextCompacting, ContextCompacted,
    FileReadEvent,
    ErrorEvent,
    ToolStatus as EventToolStatus,
)
from src.core.protocol import (
    ApprovalResult,
    InterruptSignal,
    RetrySignal,
    PauseResult,
    ClarifyResult,
    PlanApprovalResult,
)
from src.core.tool_status import ToolStatus
from src.session.store.memory_store import (
    StoreNotification,
    StoreEvent,
    ToolExecutionState,
)
from src.server.serializers import (
    serialize_event,
    serialize_store_notification,
    serialize_tool_status,
    deserialize_action,
)


# ============================================================================
# UIEvent Serialization
# ============================================================================

class TestSerializeEvent:
    """Test serialize_event() for all UIEvent types."""

    def test_stream_start(self):
        result = serialize_event(StreamStart())
        assert result == {"type": "stream_start"}

    def test_stream_end(self):
        result = serialize_event(StreamEnd(total_tokens=100, duration_ms=500))
        assert result == {
            "type": "stream_end",
            "total_tokens": 100,
            "duration_ms": 500,
        }

    def test_stream_end_none_fields(self):
        result = serialize_event(StreamEnd())
        assert result["type"] == "stream_end"
        assert result["total_tokens"] is None
        assert result["duration_ms"] is None

    def test_text_delta(self):
        result = serialize_event(TextDelta(content="Hello world"))
        assert result == {"type": "text_delta", "content": "Hello world"}

    def test_text_delta_empty(self):
        result = serialize_event(TextDelta(content=""))
        assert result == {"type": "text_delta", "content": ""}

    def test_code_block_start(self):
        result = serialize_event(CodeBlockStart(language="python"))
        assert result == {"type": "code_block_start", "language": "python"}

    def test_code_block_start_empty_language(self):
        result = serialize_event(CodeBlockStart(language=""))
        # CodeBlockStart normalizes empty to "text"
        assert result == {"type": "code_block_start", "language": "text"}

    def test_code_block_delta(self):
        result = serialize_event(CodeBlockDelta(content="def foo():"))
        assert result == {"type": "code_block_delta", "content": "def foo():"}

    def test_code_block_end(self):
        result = serialize_event(CodeBlockEnd())
        assert result == {"type": "code_block_end"}

    def test_thinking_start(self):
        result = serialize_event(ThinkingStart())
        assert result == {"type": "thinking_start"}

    def test_thinking_delta(self):
        result = serialize_event(ThinkingDelta(content="analyzing..."))
        assert result == {"type": "thinking_delta", "content": "analyzing..."}

    def test_thinking_end(self):
        result = serialize_event(ThinkingEnd(token_count=342))
        assert result == {"type": "thinking_end", "token_count": 342}

    def test_thinking_end_none(self):
        result = serialize_event(ThinkingEnd())
        assert result["token_count"] is None

    def test_pause_prompt_start(self):
        result = serialize_event(PausePromptStart(
            reason="Tool call budget reached",
            reason_code="tool_budget",
            pending_todos=["task1", "task2"],
            stats={"tool_calls": 20, "tool_budget": 20},
        ))
        assert result["type"] == "pause_prompt_start"
        assert result["reason"] == "Tool call budget reached"
        assert result["reason_code"] == "tool_budget"
        assert result["pending_todos"] == ["task1", "task2"]
        assert result["stats"]["tool_calls"] == 20

    def test_pause_prompt_end(self):
        result = serialize_event(PausePromptEnd(
            continue_work=True,
            feedback="Focus on auth",
        ))
        assert result == {
            "type": "pause_prompt_end",
            "continue_work": True,
            "feedback": "Focus on auth",
        }

    def test_context_updated(self):
        result = serialize_event(ContextUpdated(
            used=45000,
            limit=128000,
            pressure_level="green",
        ))
        assert result == {
            "type": "context_updated",
            "used": 45000,
            "limit": 128000,
            "pressure_level": "green",
            "iteration": None,
        }

    def test_context_compacting(self):
        result = serialize_event(ContextCompacting(tokens_before=120000))
        assert result == {
            "type": "context_compacting",
            "tokens_before": 120000,
        }

    def test_context_compacted(self):
        result = serialize_event(ContextCompacted(
            messages_removed=5,
            tokens_before=120000,
            tokens_after=80000,
        ))
        assert result == {
            "type": "context_compacted",
            "messages_removed": 5,
            "tokens_before": 120000,
            "tokens_after": 80000,
        }

    def test_file_read_event(self):
        result = serialize_event(FileReadEvent(
            path="src/core/agent.py",
            lines_read=200,
            truncated=False,
        ))
        assert result == {
            "type": "file_read",
            "path": "src/core/agent.py",
            "lines_read": 200,
            "truncated": False,
        }

    def test_error_event(self):
        result = serialize_event(ErrorEvent(
            error_type="rate_limit",
            user_message="Rate limited. Retrying in 30 seconds...",
            error_id="err-789",
            recoverable=True,
            retry_after=30,
        ))
        assert result["type"] == "error"
        assert result["error_type"] == "rate_limit"
        assert result["recoverable"] is True
        assert result["retry_after"] == 30

    # Legacy types should return None
    def test_legacy_tool_call_start_returns_none(self):
        result = serialize_event(ToolCallStart(
            call_id="c1", name="edit_file",
            arguments={}, requires_approval=True,
        ))
        assert result is None

    def test_legacy_tool_call_status_returns_none(self):
        result = serialize_event(ToolCallStatus(
            call_id="c1", status=EventToolStatus.RUNNING,
        ))
        assert result is None

    def test_legacy_tool_call_result_returns_none(self):
        result = serialize_event(ToolCallResult(
            call_id="c1", status=EventToolStatus.SUCCESS,
        ))
        assert result is None


# ============================================================================
# ToolStatus Serialization
# ============================================================================

class TestSerializeToolStatus:
    """Test serialize_tool_status() normalizes correctly."""

    def test_success(self):
        assert serialize_tool_status(ToolStatus.SUCCESS) == "success"

    def test_error(self):
        assert serialize_tool_status(ToolStatus.ERROR) == "error"

    def test_pending(self):
        assert serialize_tool_status(ToolStatus.PENDING) == "pending"

    def test_awaiting_approval(self):
        assert serialize_tool_status(ToolStatus.AWAITING_APPROVAL) == "awaiting_approval"

    def test_running(self):
        assert serialize_tool_status(ToolStatus.RUNNING) == "running"

    def test_events_failed_normalizes_to_error(self):
        """events.py has FAILED; wire protocol normalizes to 'error'."""
        assert serialize_tool_status(EventToolStatus.FAILED) == "error"


# ============================================================================
# StoreNotification Serialization
# ============================================================================

class TestSerializeStoreNotification:
    """Test serialize_store_notification() for all relevant event types."""

    def test_tool_state_updated_basic(self):
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_123",
            tool_state=ToolExecutionState(status=ToolStatus.RUNNING),
            metadata={"tool_name": "edit_file"},
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "store"
        assert result["event"] == "tool_state_updated"
        assert result["data"]["call_id"] == "call_123"
        assert result["data"]["status"] == "running"
        assert result["data"]["tool_name"] == "edit_file"

    def test_tool_state_updated_with_result(self):
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_456",
            tool_state=ToolExecutionState(
                status=ToolStatus.SUCCESS,
                result="File edited successfully",
                duration_ms=45,
            ),
            metadata={"tool_name": "edit_file"},
        )
        result = serialize_store_notification(notification)
        assert result["data"]["status"] == "success"
        assert result["data"]["result"] == "File edited successfully"
        assert result["data"]["duration_ms"] == 45

    def test_tool_state_updated_with_error(self):
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_789",
            tool_state=ToolExecutionState(
                status=ToolStatus.ERROR,
                error="File not found",
                duration_ms=12,
            ),
        )
        result = serialize_store_notification(notification)
        assert result["data"]["status"] == "error"
        assert result["data"]["error"] == "File not found"

    def test_tool_state_updated_no_state_returns_none(self):
        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_000",
            tool_state=None,
        )
        assert serialize_store_notification(notification) is None

    def test_message_finalized(self):
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_FINALIZED,
            metadata={"stream_id": "stream-abc"},
        )
        result = serialize_store_notification(notification)
        assert result == {
            "type": "store",
            "event": "message_finalized",
            "data": {"stream_id": "stream-abc"},
        }

    def test_bulk_load_complete_returns_none(self):
        notification = StoreNotification(
            event=StoreEvent.BULK_LOAD_COMPLETE,
        )
        assert serialize_store_notification(notification) is None

    def test_store_cleared_returns_none(self):
        notification = StoreNotification(
            event=StoreEvent.STORE_CLEARED,
        )
        assert serialize_store_notification(notification) is None


# ============================================================================
# VS Code Data Path Parity Tests
#
# These tests verify the full serialization path that VS Code relies on:
#   subagent update_tool_state -> StoreNotification -> serialize -> JSON
#
# Catches divergence between agent.py and subagent.py metadata shapes,
# and ensures message_added events serialize properly for subagent text.
# ============================================================================

class TestVSCodeDataPathParity:
    """Integration tests for the subagent -> serializer -> VS Code data path.

    These tests exist because bugs #3 and #4 (subagent tool card missing file path,
    subagent text not shown) were caused by the subagent emitting different metadata
    than what the serializer expected. If you change build_tool_metadata() or
    serialize_store_notification(), these tests should catch regressions.
    """

    def test_subagent_tool_state_includes_arguments(self):
        """build_tool_metadata() output must serialize with 'arguments' key.

        This is the exact data shape the VS Code webview's getPrimaryArg()
        needs to show file paths in tool cards.
        """
        from src.core.tool_metadata import build_tool_metadata

        metadata = build_tool_metadata(
            "read_file",
            {"file_path": "/src/main.py", "encoding": "utf-8"},
            args_summary="read_file(/src/main.py)",
        )

        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_sa_001",
            tool_state=ToolExecutionState(status=ToolStatus.RUNNING),
            metadata={"tool_name": "read_file", **metadata},
        )
        result = serialize_store_notification(notification)

        assert result is not None
        assert result["data"]["tool_name"] == "read_file"
        assert result["data"]["arguments"]["file_path"] == "/src/main.py"

    def test_subagent_tool_state_includes_requires_approval(self):
        """Approval flag must survive serialization for VS Code approval buttons."""
        from src.core.tool_metadata import build_tool_metadata

        metadata = build_tool_metadata(
            "write_file",
            {"file_path": "/src/out.py", "content": "..."},
            requires_approval=True,
        )

        notification = StoreNotification(
            event=StoreEvent.TOOL_STATE_UPDATED,
            tool_call_id="call_sa_002",
            tool_state=ToolExecutionState(status=ToolStatus.AWAITING_APPROVAL),
            metadata={"tool_name": "write_file", **metadata},
        )
        result = serialize_store_notification(notification)

        assert result["data"]["requires_approval"] is True
        assert result["data"]["arguments"]["file_path"] == "/src/out.py"

    def test_message_added_serializes_content_for_subagent_text(self):
        """MESSAGE_ADDED must serialize content so VS Code can render subagent text.

        Bug #4 was caused by the webview silently dropping these events.
        This test ensures the serializer at least emits them correctly.
        """
        from src.session.models.message import Message

        msg = Message.create_assistant(
            content="I'll start by reading the project structure.",
            session_id="test-session",
            parent_uuid="parent-001",
            seq=1,
        )

        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)

        assert result is not None
        assert result["type"] == "store"
        assert result["event"] == "message_added"
        assert result["data"]["role"] == "assistant"
        assert result["data"]["content"] == "I'll start by reading the project structure."
        assert result["data"]["uuid"] == msg.uuid

    def test_message_added_user_task_serializes(self):
        """The initial task message (user role) must also serialize for subagent display."""
        from src.session.models.message import Message

        msg = Message.create_user(
            content="Explore the codebase and summarize the architecture.",
            session_id="test-session",
            parent_uuid="",
            seq=0,
        )

        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)

        assert result is not None
        assert result["data"]["role"] == "user"
        assert "architecture" in result["data"]["content"]

    def test_build_tool_metadata_parity_with_agent(self):
        """build_tool_metadata output must match what agent.py used to pass directly.

        Agent.py used to pass: {"arguments": tool_args, "requires_approval": bool}
        build_tool_metadata must produce a superset of that shape.
        """
        from src.core.tool_metadata import build_tool_metadata

        result = build_tool_metadata(
            "edit_file",
            {"file_path": "/foo.py", "old_string": "a", "new_string": "b"},
            args_summary="edit_file(/foo.py)",
            requires_approval=True,
        )

        # Must contain the keys the serializer extracts
        assert "arguments" in result
        assert result["arguments"]["file_path"] == "/foo.py"
        assert "requires_approval" in result
        assert result["requires_approval"] is True
        # Must also contain args_summary for TUI SubAgentCard
        assert "args_summary" in result


# ============================================================================
# UserAction Deserialization
# ============================================================================

class TestDeserializeAction:
    """Test deserialize_action() for all UserAction types."""

    def test_approval_result_approved(self):
        data = {"type": "approval_result", "call_id": "c1", "approved": True}
        result = deserialize_action(data)
        assert isinstance(result, ApprovalResult)
        assert result.call_id == "c1"
        assert result.approved is True
        assert result.auto_approve_future is False  # default

    def test_approval_result_rejected_with_feedback(self):
        data = {
            "type": "approval_result",
            "call_id": "c2",
            "approved": False,
            "feedback": "Do not modify that file",
        }
        result = deserialize_action(data)
        assert isinstance(result, ApprovalResult)
        assert result.approved is False
        assert result.feedback == "Do not modify that file"

    def test_approval_result_auto_approve(self):
        data = {
            "type": "approval_result",
            "call_id": "c3",
            "approved": True,
            "auto_approve_future": True,
        }
        result = deserialize_action(data)
        assert result.auto_approve_future is True

    def test_interrupt_signal(self):
        result = deserialize_action({"type": "interrupt"})
        assert isinstance(result, InterruptSignal)

    def test_retry_signal(self):
        result = deserialize_action({"type": "retry"})
        assert isinstance(result, RetrySignal)

    def test_pause_result(self):
        data = {
            "type": "pause_result",
            "continue_work": True,
            "feedback": "Focus on auth",
        }
        result = deserialize_action(data)
        assert isinstance(result, PauseResult)
        assert result.continue_work is True
        assert result.feedback == "Focus on auth"

    def test_clarify_result(self):
        data = {
            "type": "clarify_result",
            "call_id": "cl1",
            "submitted": True,
            "responses": {"q1": "option_a"},
        }
        result = deserialize_action(data)
        assert isinstance(result, ClarifyResult)
        assert result.call_id == "cl1"
        assert result.submitted is True
        assert result.responses == {"q1": "option_a"}

    def test_plan_approval_result(self):
        data = {
            "type": "plan_approval_result",
            "plan_hash": "sha256-abc",
            "approved": True,
            "auto_accept_edits": True,
        }
        result = deserialize_action(data)
        assert isinstance(result, PlanApprovalResult)
        assert result.plan_hash == "sha256-abc"
        assert result.approved is True
        assert result.auto_accept_edits is True

    def test_unknown_type_returns_none(self):
        result = deserialize_action({"type": "unknown_future_message"})
        assert result is None

    def test_empty_dict_returns_none(self):
        result = deserialize_action({})
        assert result is None

    def test_missing_type_returns_none(self):
        result = deserialize_action({"call_id": "c1", "approved": True})
        assert result is None


# ============================================================================
# Interactive Notification Serialization
# ============================================================================

class TestSerializeInteractiveNotifications:
    """Test serialize_store_notification() for interactive system events."""

    def _make_system_message(self, event_type, extra, content="[event]"):
        """Helper to create a system Message with event_type and extra."""
        from src.session.models.message import Message, MessageMeta
        return Message(
            role="system",
            content=content,
            meta=MessageMeta(
                uuid="msg-test-123",
                event_type=event_type,
                include_in_llm_context=False,
                extra=extra,
            ),
        )

    def test_clarify_request(self):
        msg = self._make_system_message(
            event_type="clarify_request",
            extra={
                "call_id": "cl_001",
                "questions": [
                    {"id": "q1", "label": "Framework", "question": "Which framework?", "options": ["React", "Vue"]},
                ],
                "context": "Need to know before proceeding",
            },
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["event"] == "clarify_request"
        assert result["data"]["uuid"] == "msg-test-123"
        assert result["data"]["call_id"] == "cl_001"
        assert len(result["data"]["questions"]) == 1
        assert result["data"]["questions"][0]["id"] == "q1"
        assert result["data"]["context"] == "Need to know before proceeding"

    def test_plan_submitted(self):
        msg = self._make_system_message(
            event_type="plan_submitted",
            extra={
                "call_id": "pl_001",
                "plan_hash": "sha256-abc",
                "excerpt": "## Plan\n1. Step one\n2. Step two",
                "truncated": False,
                "plan_path": ".claraity/plans/plan.md",
            },
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["event"] == "plan_submitted"
        assert result["data"]["uuid"] == "msg-test-123"
        assert result["data"]["call_id"] == "pl_001"
        assert result["data"]["plan_hash"] == "sha256-abc"
        assert result["data"]["excerpt"].startswith("## Plan")
        assert result["data"]["truncated"] is False
        assert result["data"]["plan_path"] == ".claraity/plans/plan.md"

    def test_director_plan_submitted(self):
        msg = self._make_system_message(
            event_type="director_plan_submitted",
            extra={
                "call_id": "dp_001",
                "plan_hash": "sha256-def",
                "excerpt": "## Director Plan\nSlice 1: Auth",
                "truncated": False,
            },
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["event"] == "director_plan_submitted"
        assert result["data"]["call_id"] == "dp_001"
        assert result["data"]["plan_hash"] == "sha256-def"
        assert result["data"]["plan_path"] is None  # not provided

    def test_clarify_request_missing_extra_defaults(self):
        """clarify_request with empty extra still serializes with defaults."""
        msg = self._make_system_message(
            event_type="clarify_request",
            extra={},
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["data"]["call_id"] == ""
        assert result["data"]["questions"] == []
        assert result["data"]["context"] is None

    def test_plan_submitted_none_extra_defaults(self):
        """plan_submitted with None extra still serializes with defaults."""
        msg = self._make_system_message(
            event_type="plan_submitted",
            extra=None,
        )
        # extra=None in MessageMeta, so meta.extra is None
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["data"]["plan_hash"] == ""
        assert result["data"]["excerpt"] == ""

    def test_permission_mode_changed(self):
        msg = self._make_system_message(
            event_type="permission_mode_changed",
            extra={
                "old_mode": "normal",
                "new_mode": "auto",
            },
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["event"] == "permission_mode_changed"
        assert result["data"]["uuid"] == "msg-test-123"
        assert result["data"]["old_mode"] == "normal"
        assert result["data"]["new_mode"] == "auto"

    def test_permission_mode_changed_empty_extra(self):
        """permission_mode_changed with empty extra still serializes with defaults."""
        msg = self._make_system_message(
            event_type="permission_mode_changed",
            extra={},
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "interactive"
        assert result["event"] == "permission_mode_changed"
        assert result["data"]["old_mode"] == ""
        assert result["data"]["new_mode"] == ""

    def test_unknown_system_event_falls_through(self):
        """System events with unrecognized event_type fall through to generic."""
        msg = self._make_system_message(
            event_type="turn_duration",
            extra={"elapsed_ms": 5000},
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "store"
        assert result["event"] == "message_added"
        assert result["data"]["role"] == "system"

    def test_regular_message_not_affected(self):
        """Non-system messages in MESSAGE_ADDED are unaffected."""
        from src.session.models.message import Message, MessageMeta
        msg = Message(
            role="user",
            content="Hello",
            meta=MessageMeta(uuid="msg-user-1", stream_id="s1"),
        )
        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=msg,
        )
        result = serialize_store_notification(notification)
        assert result["type"] == "store"
        assert result["event"] == "message_added"
        assert result["data"]["uuid"] == "msg-user-1"
        assert result["data"]["content"] == "Hello"
