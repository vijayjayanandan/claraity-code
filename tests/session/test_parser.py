"""Tests for JSONL parser (Schema v2.1)."""

import pytest
import json
import tempfile
from pathlib import Path

from src.session.persistence import (
    ParseError,
    parse_line,
    parse_file_iter,
    load_session,
    validate_session_file,
    get_session_info,
)
from src.session.models import Message, FileHistorySnapshot
from src.session.store import MessageStore


class TestParseLine:
    """Tests for single line parsing."""

    def test_parse_user_message(self):
        data = {
            "role": "user",
            "content": "Hello",
            "meta": {
                "uuid": "msg-1",
                "seq": 0,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": None,
                "is_sidechain": False
            }
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=1)

        assert isinstance(result, Message)
        assert result.role == "user"
        assert result.content == "Hello"
        assert result.seq == 1  # From line_number

    def test_parse_assistant_message(self):
        data = {
            "role": "assistant",
            "content": "Hi there!",
            "meta": {
                "uuid": "msg-2",
                "seq": 0,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": "msg-1",
                "is_sidechain": False,
                "stream_id": "stream_001"
            }
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=2)

        assert isinstance(result, Message)
        assert result.role == "assistant"
        assert result.stream_id == "stream_001"

    def test_parse_tool_message(self):
        data = {
            "role": "tool",
            "content": "File content here",
            "tool_call_id": "call_123",
            "meta": {
                "uuid": "msg-3",
                "seq": 0,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": "msg-2",
                "is_sidechain": False,
                "status": "success"
            }
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=3)

        assert isinstance(result, Message)
        assert result.role == "tool"
        assert result.tool_call_id == "call_123"

    def test_parse_system_message(self):
        data = {
            "role": "system",
            "content": "System prompt",
            "meta": {
                "uuid": "msg-0",
                "seq": 0,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": None,
                "is_sidechain": False
            }
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=1)

        assert isinstance(result, Message)
        assert result.role == "system"

    def test_parse_file_snapshot(self):
        data = {
            "type": "file_snapshot",
            "uuid": "snap-1",
            "timestamp": "2024-01-01T00:00:00Z",
            "session_id": "sess-1",
            "snapshots": [],
            "backups": []
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=1)

        assert isinstance(result, FileHistorySnapshot)
        assert result.uuid == "snap-1"

    def test_parse_invalid_json_raises_error(self):
        with pytest.raises(ParseError) as exc_info:
            parse_line("not valid json", line_number=1)
        assert "Invalid JSON" in str(exc_info.value)
        assert exc_info.value.line_number == 1

    def test_parse_missing_role_raises_error(self):
        data = {"content": "Hello", "meta": {}}
        line = json.dumps(data)
        with pytest.raises(ParseError) as exc_info:
            parse_line(line, line_number=1)
        assert "Missing 'role' field" in str(exc_info.value)

    def test_parse_unknown_role_returns_none(self):
        data = {
            "role": "unknown_role",
            "content": "Hello",
            "meta": {}
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=1)
        assert result is None

    def test_parse_with_tool_calls(self):
        data = {
            "role": "assistant",
            "content": "Let me read that file.",
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "Read",
                        "arguments": "{\"file_path\": \"test.py\"}"
                    }
                }
            ],
            "meta": {
                "uuid": "msg-1",
                "seq": 0,
                "timestamp": "2024-01-01T00:00:00Z",
                "session_id": "sess-1",
                "parent_uuid": None,
                "is_sidechain": False
            }
        }
        line = json.dumps(data)
        result = parse_line(line, line_number=1)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].function.name == "Read"


class TestParseFileIter:
    """Tests for streaming file parsing."""

    def test_parse_file_iter_basic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data1 = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            data2 = {"role": "assistant", "content": "Hi!", "meta": {"uuid": "m2", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": "m1", "is_sidechain": False}}
            f.write(json.dumps(data1) + "\n")
            f.write(json.dumps(data2) + "\n")
            f.flush()

            results = list(parse_file_iter(f.name))

            assert len(results) == 2
            assert results[0][0] == 1  # Line number
            assert results[0][1].role == "user"
            assert results[1][0] == 2
            assert results[1][1].role == "assistant"

        Path(f.name).unlink()

    def test_parse_file_iter_skips_empty_lines(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.write("\n")  # Empty line
            f.write("   \n")  # Whitespace only
            f.flush()

            results = list(parse_file_iter(f.name))
            assert len(results) == 1

        Path(f.name).unlink()

    def test_parse_file_iter_skips_unknown_types(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data1 = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            data2 = {"role": "unknown", "content": "Skip me", "meta": {}}
            data3 = {"role": "assistant", "content": "Hi!", "meta": {"uuid": "m2", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data1) + "\n")
            f.write(json.dumps(data2) + "\n")
            f.write(json.dumps(data3) + "\n")
            f.flush()

            results = list(parse_file_iter(f.name))
            assert len(results) == 2

        Path(f.name).unlink()

    def test_parse_file_iter_tolerant_last_line(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.write('{"truncated": true')  # Incomplete JSON
            f.flush()

            # Should not raise, just skip last line
            results = list(parse_file_iter(f.name, tolerant_last_line=True))
            assert len(results) == 1

        Path(f.name).unlink()

    def test_parse_file_iter_strict_last_line(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.write('{"truncated": true')  # Incomplete JSON
            f.flush()

            with pytest.raises(ParseError):
                list(parse_file_iter(f.name, tolerant_last_line=False))

        Path(f.name).unlink()

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            list(parse_file_iter("/nonexistent/path.jsonl"))


class TestLoadSession:
    """Tests for full session loading."""

    def test_load_session_basic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data1 = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            data2 = {"role": "assistant", "content": "Hi!", "meta": {"uuid": "m2", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": "m1", "is_sidechain": False, "stream_id": "str1"}}
            f.write(json.dumps(data1) + "\n")
            f.write(json.dumps(data2) + "\n")
            f.flush()

            store = load_session(f.name)

            assert store.message_count == 2
            assert store.session_id == "s1"

        Path(f.name).unlink()

    def test_load_session_with_existing_store(self):
        store = MessageStore()
        # Pre-populate at seq=100 to avoid collision with line-number based seq
        msg = Message.create_user("Pre-existing", "s0", None, 100)
        store.add_message(msg)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "New", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.flush()

            result = load_session(f.name, store=store)

            assert result is store
            assert store.message_count == 2

        Path(f.name).unlink()

    def test_load_session_with_progress_callback(self):
        progress_calls = []

        def on_progress(current, total):
            progress_calls.append((current, total))

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            for i in range(5):
                data = {"role": "user", "content": f"Msg {i}", "meta": {"uuid": f"m{i}", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
                f.write(json.dumps(data) + "\n")
            f.flush()

            load_session(f.name, on_progress=on_progress)

            assert len(progress_calls) == 5
            assert progress_calls[-1] == (5, 5)

        Path(f.name).unlink()

    def test_load_session_handles_snapshots(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            msg = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            snap = {"type": "file_snapshot", "uuid": "snap1", "timestamp": "", "session_id": "s1", "snapshots": [], "backups": []}
            f.write(json.dumps(msg) + "\n")
            f.write(json.dumps(snap) + "\n")
            f.flush()

            store = load_session(f.name)

            assert store.message_count == 1
            assert store.get_snapshot("snap1") is not None

        Path(f.name).unlink()


class TestValidateSessionFile:
    """Tests for session file validation."""

    def test_validate_valid_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 0, "timestamp": "", "session_id": "s1", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.flush()

            is_valid, errors = validate_session_file(f.name)

            assert is_valid == True
            assert errors == []

        Path(f.name).unlink()

    def test_validate_invalid_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write("not valid json\n")
            f.flush()

            is_valid, errors = validate_session_file(f.name)

            assert is_valid == False
            assert len(errors) > 0

        Path(f.name).unlink()

    def test_validate_nonexistent_file(self):
        is_valid, errors = validate_session_file("/nonexistent/path.jsonl")
        assert is_valid == False
        assert "not found" in errors[0].lower()


class TestGetSessionInfo:
    """Tests for quick session info extraction."""

    def test_get_session_info(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            data = {"role": "user", "content": "Hello", "meta": {"uuid": "m1", "seq": 1, "timestamp": "2024-01-01T00:00:00Z", "session_id": "test-session", "parent_uuid": None, "is_sidechain": False}}
            f.write(json.dumps(data) + "\n")
            f.write(json.dumps(data) + "\n")
            f.write(json.dumps(data) + "\n")
            f.flush()

            info = get_session_info(f.name)

            assert info is not None
            assert info["session_id"] == "test-session"
            assert info["first_timestamp"] == "2024-01-01T00:00:00Z"
            assert info["line_count"] == 3

        Path(f.name).unlink()

    def test_get_session_info_nonexistent(self):
        info = get_session_info("/nonexistent/path.jsonl")
        assert info is None

    def test_get_session_info_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.flush()

            info = get_session_info(f.name)

            assert info is not None
            assert info["line_count"] == 0
            assert info["session_id"] is None

        Path(f.name).unlink()
