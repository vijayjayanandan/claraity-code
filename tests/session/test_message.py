"""Tests for unified Message class (Schema v2.1)."""

import pytest
import json
from src.session.models import (
    Message,
    MessageMeta,
    ToolCall,
    ToolCallFunction,
    TokenUsage,
    TextSegment,
    ToolCallSegment,
    ThinkingSegment,
    Segment,
    parse_segment,
    FileHistorySnapshot,
    Snapshot,
    FileBackup,
    SCHEMA_VERSION,
    generate_uuid,
    now_iso,
    generate_stream_id,
    generate_tool_call_id,
)


class TestSegmentTypes:
    """Tests for segment types used in content ordering."""

    def test_text_segment_creation(self):
        seg = TextSegment(content="Hello world")
        assert seg.type == "text"
        assert seg.content == "Hello world"

    def test_text_segment_serialization(self):
        seg = TextSegment(content="Hello")
        d = seg.to_dict()
        assert d == {"type": "text", "content": "Hello"}

    def test_text_segment_deserialization(self):
        seg = TextSegment.from_dict({"content": "Hello"})
        assert seg.content == "Hello"
        assert seg.type == "text"

    def test_tool_call_segment_creation(self):
        seg = ToolCallSegment(tool_call_index=0)
        assert seg.type == "tool_call"
        assert seg.tool_call_index == 0

    def test_tool_call_segment_serialization(self):
        seg = ToolCallSegment(tool_call_index=2)
        d = seg.to_dict()
        assert d == {"type": "tool_call", "tool_call_index": 2}

    def test_thinking_segment_creation(self):
        seg = ThinkingSegment(content="Let me think...")
        assert seg.type == "thinking"
        assert seg.content == "Let me think..."

    def test_parse_segment_text(self):
        seg = parse_segment({"type": "text", "content": "Hello"})
        assert isinstance(seg, TextSegment)
        assert seg.content == "Hello"

    def test_parse_segment_tool_call(self):
        seg = parse_segment({"type": "tool_call", "tool_call_index": 1})
        assert isinstance(seg, ToolCallSegment)
        assert seg.tool_call_index == 1

    def test_parse_segment_thinking(self):
        seg = parse_segment({"type": "thinking", "content": "Reasoning..."})
        assert isinstance(seg, ThinkingSegment)
        assert seg.content == "Reasoning..."

    def test_parse_segment_unknown_type(self):
        # Unknown types are treated as text
        seg = parse_segment({"type": "unknown", "content": "data"})
        assert isinstance(seg, TextSegment)


class TestToolCall:
    """Tests for ToolCall class."""

    def test_tool_call_creation(self):
        func = ToolCallFunction(name="Read", arguments='{"file_path": "test.py"}')
        tc = ToolCall(id="call_123", function=func)
        assert tc.id == "call_123"
        assert tc.type == "function"
        assert tc.function.name == "Read"

    def test_tool_call_serialization(self):
        func = ToolCallFunction(name="Read", arguments='{"file_path": "test.py"}')
        tc = ToolCall(id="call_123", function=func)
        d = tc.to_dict()
        assert d["id"] == "call_123"
        assert d["type"] == "function"
        assert d["function"]["name"] == "Read"
        assert "meta" not in d  # Empty meta not included

    def test_tool_call_with_meta(self):
        func = ToolCallFunction(name="Read", arguments="{}")
        tc = ToolCall(id="call_123", function=func, meta={"custom": "data"})
        d = tc.to_dict()
        assert d["meta"] == {"custom": "data"}

    def test_tool_call_to_llm_dict_strips_meta(self):
        func = ToolCallFunction(name="Read", arguments="{}")
        tc = ToolCall(id="call_123", function=func, meta={"custom": "data"})
        d = tc.to_llm_dict()
        assert "meta" not in d

    def test_tool_call_function_get_parsed_arguments(self):
        func = ToolCallFunction(name="Read", arguments='{"file_path": "test.py"}')
        args = func.get_parsed_arguments()
        assert args == {"file_path": "test.py"}

    def test_tool_call_function_invalid_json(self):
        func = ToolCallFunction(name="Read", arguments="invalid json")
        args = func.get_parsed_arguments()
        assert args == {}

    def test_tool_call_deserialization(self):
        data = {
            "id": "call_456",
            "type": "function",
            "function": {"name": "Write", "arguments": "{}"}
        }
        tc = ToolCall.from_dict(data)
        assert tc.id == "call_456"
        assert tc.function.name == "Write"


class TestCanonicalToolCallIds:
    """Tests for canonical tool call ID generation."""

    def test_generate_tool_call_id_format(self):
        tc_id = generate_tool_call_id()
        assert tc_id.startswith("tc_")
        assert len(tc_id) == 35
        # All chars after prefix should be lowercase hex
        assert all(c in "0123456789abcdef" for c in tc_id[3:])

    def test_generate_tool_call_id_unique(self):
        ids = {generate_tool_call_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_generate_tool_call_id_provider_safe(self):
        """ID should satisfy all provider regex patterns."""
        import re
        tc_id = generate_tool_call_id()
        # Anthropic: ^[a-zA-Z0-9_-]+$
        assert re.match(r"^[a-zA-Z0-9_-]+$", tc_id)
        # OpenAI: max 40 chars
        assert len(tc_id) <= 40
        # Mistral: min 9 chars
        assert len(tc_id) >= 9

    def test_from_provider_preserves_provider_id(self):
        func = ToolCallFunction(name="read_file", arguments="{}")
        tc = ToolCall.from_provider(provider_id="toolu_abc123", function=func)
        assert tc.id.startswith("tc_")
        assert tc.meta["provider_tool_id"] == "toolu_abc123"
        assert tc.function.name == "read_file"

    def test_from_provider_different_from_constructor(self):
        """from_provider generates canonical ID; constructor preserves given ID."""
        func = ToolCallFunction(name="read_file", arguments="{}")
        # Constructor: preserves exact ID (used for JSONL deserialization)
        tc_direct = ToolCall(id="call_xyz", function=func)
        assert tc_direct.id == "call_xyz"
        # Factory: generates canonical ID (used for new provider responses)
        tc_factory = ToolCall.from_provider(provider_id="call_xyz", function=func)
        assert tc_factory.id.startswith("tc_")
        assert tc_factory.id != "call_xyz"

    def test_from_dict_preserves_stored_id(self):
        """Deserialization from JSONL should NOT generate new IDs."""
        data = {
            "id": "tc_abcdef1234567890abcdef1234567890",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{}"},
            "meta": {"provider_tool_id": "toolu_old"},
        }
        tc = ToolCall.from_dict(data)
        assert tc.id == "tc_abcdef1234567890abcdef1234567890"
        assert tc.meta["provider_tool_id"] == "toolu_old"


class TestTokenUsage:
    """Tests for TokenUsage class."""

    def test_token_usage_creation(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_token_usage_with_cache(self):
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_write_tokens=10
        )
        d = usage.to_dict()
        assert d["cache_read_tokens"] == 20
        assert d["cache_write_tokens"] == 10

    def test_token_usage_serialization_excludes_none(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        d = usage.to_dict()
        assert "cache_read_tokens" not in d
        assert "reasoning_tokens" not in d


class TestMessageMeta:
    """Tests for MessageMeta class."""

    def test_meta_creation_with_required_fields(self):
        meta = MessageMeta(
            uuid="msg-123",
            seq=1,
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-456",
            parent_uuid=None,
            is_sidechain=False
        )
        assert meta.uuid == "msg-123"
        assert meta.seq == 1
        assert meta.schema_version == SCHEMA_VERSION

    def test_meta_serialization(self):
        meta = MessageMeta(
            uuid="msg-123",
            seq=1,
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-456",
            parent_uuid="parent-789",
            is_sidechain=False
        )
        d = meta.to_dict()
        assert d["uuid"] == "msg-123"
        assert d["parent_uuid"] == "parent-789"
        assert d["schema_version"] == SCHEMA_VERSION

    def test_meta_optional_fields_excluded_when_none(self):
        meta = MessageMeta(
            uuid="msg-123",
            seq=1,
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-456",
            parent_uuid=None,
            is_sidechain=False
        )
        d = meta.to_dict()
        assert "stream_id" not in d
        assert "thinking" not in d
        assert "usage" not in d

    def test_meta_with_segments(self):
        segments = [
            TextSegment(content="Hello"),
            ToolCallSegment(tool_call_index=0)
        ]
        meta = MessageMeta(
            uuid="msg-123",
            seq=1,
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-456",
            parent_uuid=None,
            is_sidechain=False,
            segments=segments
        )
        d = meta.to_dict()
        assert len(d["segments"]) == 2
        assert d["segments"][0]["type"] == "text"

    def test_meta_deserialization(self):
        data = {
            "uuid": "msg-123",
            "seq": 5,
            "timestamp": "2024-01-01T00:00:00Z",
            "session_id": "sess-456",
            "parent_uuid": None,
            "is_sidechain": True,
            "stream_id": "stream_001",
            "thinking": "Let me reason..."
        }
        meta = MessageMeta.from_dict(data)
        assert meta.uuid == "msg-123"
        assert meta.seq == 5
        assert meta.is_sidechain == True
        assert meta.stream_id == "stream_001"
        assert meta.thinking == "Let me reason..."


class TestMessage:
    """Tests for unified Message class."""

    def test_message_creation_basic(self):
        msg = Message(
            role="user",
            content="Hello",
            meta=MessageMeta(
                uuid="msg-1",
                seq=1,
                timestamp="2024-01-01T00:00:00Z",
                session_id="sess-1",
                parent_uuid=None,
                is_sidechain=False
            )
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.uuid == "msg-1"

    def test_create_user_factory(self):
        msg = Message.create_user(
            content="Hello",
            session_id="sess-1",
            parent_uuid=None,
            seq=1
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.is_user == True
        assert msg.uuid != ""
        assert msg.seq == 1

    def test_create_assistant_factory(self):
        msg = Message.create_assistant(
            content="Hi there!",
            session_id="sess-1",
            parent_uuid="msg-1",
            seq=2
        )
        assert msg.role == "assistant"
        assert msg.is_assistant == True
        assert msg.stream_id is not None

    def test_create_assistant_with_tool_calls(self):
        tc = ToolCall(
            id="call_123",
            function=ToolCallFunction(name="Read", arguments="{}")
        )
        msg = Message.create_assistant(
            content="Let me read that.",
            session_id="sess-1",
            parent_uuid="msg-1",
            seq=2,
            tool_calls=[tc]
        )
        assert len(msg.tool_calls) == 1
        assert msg.get_tool_call_ids() == ["call_123"]
        assert msg.has_tool_calls() == True

    def test_create_tool_factory(self):
        msg = Message.create_tool(
            tool_call_id="call_123",
            content="File content here",
            session_id="sess-1",
            parent_uuid="msg-2",
            seq=3,
            status="success",
            duration_ms=50
        )
        assert msg.role == "tool"
        assert msg.is_tool == True
        assert msg.tool_call_id == "call_123"
        assert msg.meta.status == "success"
        assert msg.meta.duration_ms == 50

    def test_create_system_factory(self):
        msg = Message.create_system(
            content="System message",
            session_id="sess-1",
            seq=1,
            event_type="compact_boundary"
        )
        assert msg.role == "system"
        assert msg.is_system == True
        assert msg.meta.event_type == "compact_boundary"

    def test_to_dict_serialization(self):
        msg = Message.create_user(
            content="Hello",
            session_id="sess-1",
            parent_uuid=None,
            seq=1
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert "meta" in d
        assert d["meta"]["session_id"] == "sess-1"

    def test_to_llm_dict_strips_meta(self):
        msg = Message.create_user(
            content="Hello",
            session_id="sess-1",
            parent_uuid=None,
            seq=1
        )
        d = msg.to_llm_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert "meta" not in d

    def test_to_llm_dict_includes_tool_calls(self):
        tc = ToolCall(
            id="call_123",
            function=ToolCallFunction(name="Read", arguments="{}")
        )
        msg = Message.create_assistant(
            content="Reading file",
            session_id="sess-1",
            parent_uuid=None,
            seq=1,
            tool_calls=[tc]
        )
        d = msg.to_llm_dict()
        assert "tool_calls" in d
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["id"] == "call_123"

    def test_from_dict_deserialization(self):
        data = {
            "role": "assistant",
            "content": "Hello!",
            "meta": {
                "uuid": "msg-123",
                "seq": 5,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": "msg-1",
                "is_sidechain": False,
                "stream_id": "stream_001"
            }
        }
        msg = Message.from_dict(data)
        assert msg.role == "assistant"
        assert msg.content == "Hello!"
        assert msg.uuid == "msg-123"
        assert msg.stream_id == "stream_001"

    def test_from_dict_with_seq_override(self):
        data = {
            "role": "user",
            "content": "Hello",
            "meta": {"uuid": "msg-1", "seq": 0, "timestamp": "", "session_id": "", "parent_uuid": None, "is_sidechain": False}
        }
        msg = Message.from_dict(data, seq=10)
        assert msg.seq == 10

    def test_role_check_properties(self):
        user = Message.create_user("Hi", "sess", None, 1)
        assistant = Message.create_assistant("Hello", "sess", None, 2)
        tool = Message.create_tool("call_1", "result", "sess", None, 3)
        system = Message.create_system("sys", "sess", 4)

        assert user.is_user and not user.is_assistant and not user.is_tool and not user.is_system
        assert assistant.is_assistant and not assistant.is_user
        assert tool.is_tool and not tool.is_assistant
        assert system.is_system and not system.is_user

    def test_get_collapse_key(self):
        # Only assistant messages have collapse key
        assistant = Message.create_assistant("Hi", "sess", None, 1, stream_id="stream_001")
        user = Message.create_user("Hello", "sess", None, 2)

        assert assistant.get_collapse_key() == "stream_001"
        assert user.get_collapse_key() is None

    def test_should_include_in_context(self):
        # Regular messages are included
        msg = Message.create_user("Hi", "sess", None, 1)
        assert msg.should_include_in_context == True

        # Compact boundary excluded
        boundary = Message.create_system("boundary", "sess", 2, event_type="compact_boundary")
        assert boundary.should_include_in_context == False

        # Explicit include_in_llm_context=False
        meta = MessageMeta(
            uuid="m1", seq=3, timestamp="", session_id="sess",
            parent_uuid=None, is_sidechain=False,
            include_in_llm_context=False
        )
        excluded = Message(role="user", content="test", meta=meta)
        assert excluded.should_include_in_context == False

    def test_get_ordered_content_with_segments(self):
        segments = [
            TextSegment(content="Part 1"),
            ToolCallSegment(tool_call_index=0),
            TextSegment(content="Part 2")
        ]
        meta = MessageMeta(
            uuid="m1", seq=1, timestamp="", session_id="sess",
            parent_uuid=None, is_sidechain=False,
            segments=segments
        )
        msg = Message(role="assistant", content="Part 1 Part 2", meta=meta)
        ordered = msg.get_ordered_content()
        assert len(ordered) == 3
        assert isinstance(ordered[0], TextSegment)
        assert isinstance(ordered[1], ToolCallSegment)

    def test_get_ordered_content_synthesized(self):
        tc = ToolCall(id="c1", function=ToolCallFunction(name="Read", arguments="{}"))
        msg = Message.create_assistant("Hello", "sess", None, 1, tool_calls=[tc])
        # No explicit segments, should synthesize
        ordered = msg.get_ordered_content()
        assert len(ordered) == 2
        assert isinstance(ordered[0], TextSegment)
        assert isinstance(ordered[1], ToolCallSegment)

    def test_raw_response_not_serialized(self):
        msg = Message.create_assistant("Hi", "sess", None, 1)
        msg._raw_response = {"full": "response", "data": "here"}

        d = msg.to_dict()
        assert "_raw_response" not in d
        assert "raw_response" not in d

    def test_get_text_content(self):
        msg = Message.create_user("Hello", "sess", None, 1)
        assert msg.get_text_content() == "Hello"

        empty = Message(role="user", content=None, meta=MessageMeta(
            uuid="m1", seq=1, timestamp="", session_id="",
            parent_uuid=None, is_sidechain=False
        ))
        assert empty.get_text_content() == ""


class TestFileHistorySnapshot:
    """Tests for FileHistorySnapshot class."""

    def test_snapshot_creation(self):
        snap = Snapshot(file_path="/test/file.py", content="print('hello')", hash="abc123")
        assert snap.file_path == "/test/file.py"
        assert snap.content == "print('hello')"

    def test_file_backup_creation(self):
        backup = FileBackup(file_path="/test/file.py", existed=True, content="old content")
        assert backup.existed == True

    def test_file_history_snapshot_create(self):
        fhs = FileHistorySnapshot.create(session_id="sess-1")
        assert fhs.session_id == "sess-1"
        assert fhs.uuid != ""
        assert fhs.type == "file_snapshot"

    def test_file_history_snapshot_serialization(self):
        fhs = FileHistorySnapshot(
            uuid="snap-1",
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-1",
            snapshots=[Snapshot(file_path="/f.py", content="code", hash="abc")],
            backups=[FileBackup(file_path="/f.py", existed=True, content="old")]
        )
        d = fhs.to_dict()
        assert d["type"] == "file_snapshot"
        assert d["uuid"] == "snap-1"
        assert len(d["snapshots"]) == 1
        assert len(d["backups"]) == 1

    def test_file_history_snapshot_deserialization(self):
        data = {
            "type": "file_snapshot",
            "uuid": "snap-1",
            "timestamp": "2024-01-01T00:00:00Z",
            "session_id": "sess-1",
            "snapshots": [{"file_path": "/f.py", "content": "code", "hash": "abc"}],
            "backups": [{"file_path": "/f.py", "existed": True, "content": "old"}]
        }
        fhs = FileHistorySnapshot.from_dict(data)
        assert fhs.uuid == "snap-1"
        assert len(fhs.snapshots) == 1
        assert len(fhs.backups) == 1


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_generate_uuid(self):
        uuid1 = generate_uuid()
        uuid2 = generate_uuid()
        assert uuid1 != uuid2
        assert len(uuid1) == 36  # Standard UUID format

    def test_now_iso(self):
        ts = now_iso()
        assert ts.endswith("Z")
        assert "T" in ts

    def test_generate_stream_id(self):
        sid = generate_stream_id()
        assert sid.startswith("stream_")
        assert len(sid) > 7
