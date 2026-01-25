"""
Tests for TranscriptLogger - JSONL conversation transcript logging.

Tests cover:
- Basic event logging
- Truncation of large content
- Secret redaction
- Thread safety
- Query functionality
- Sequence number continuity
"""

import json
import pytest
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from src.observability.transcript_logger import (
    TranscriptLogger,
    TranscriptEvent,
    SECRET_PATTERNS,
    SENSITIVE_KEYS
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test transcripts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def logger(temp_dir):
    """Create a TranscriptLogger for testing."""
    return TranscriptLogger(
        session_id="test-session-123",
        base_dir=temp_dir
    )


class TestBasicLogging:
    """Test basic event logging functionality."""

    def test_creates_transcript_directory(self, temp_dir):
        """Transcript directory should be created on init."""
        logger = TranscriptLogger(session_id="test", base_dir=temp_dir)
        assert (temp_dir / "transcripts").exists()

    def test_creates_transcript_file_on_first_log(self, logger):
        """Transcript file should be created on first log."""
        assert not logger.transcript_path.exists()
        logger.log("test_event", {"key": "value"})
        assert logger.transcript_path.exists()

    def test_log_creates_valid_jsonl(self, logger):
        """Each log entry should be valid JSON on its own line."""
        logger.log("event1", {"data": "one"})
        logger.log("event2", {"data": "two"})

        with open(logger.transcript_path, 'r') as f:
            lines = f.readlines()

        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "event1"
        assert json.loads(lines[1])["event"] == "event2"

    def test_log_includes_required_fields(self, logger):
        """Log entries should include all required envelope fields."""
        event = logger.log("test_event", {"key": "value"})

        assert event.v == 1
        assert event.session_id == "test-session-123"
        assert event.seq == 1
        assert event.ts.endswith("Z")
        assert event.event == "test_event"
        assert event.level == "info"
        assert event.data == {"key": "value"}

    def test_sequence_numbers_are_monotonic(self, logger):
        """Sequence numbers should increase monotonically."""
        e1 = logger.log("event1", {})
        e2 = logger.log("event2", {})
        e3 = logger.log("event3", {})

        assert e1.seq == 1
        assert e2.seq == 2
        assert e3.seq == 3


class TestConvenienceMethods:
    """Test convenience logging methods."""

    def test_log_user_message(self, logger):
        """log_user_message should log with correct event type."""
        event = logger.log_user_message("Hello, help me fix this bug")

        assert event.event == "user_message"
        assert event.data["content"] == "Hello, help me fix this bug"

    def test_log_assistant_message(self, logger):
        """log_assistant_message should log with tool_calls if provided."""
        tool_calls = [{"id": "call_123", "name": "read_file"}]
        event = logger.log_assistant_message(
            "I'll read the file",
            tool_calls=tool_calls
        )

        assert event.event == "assistant_message"
        assert event.data["content"] == "I'll read the file"
        assert event.data["tool_calls"] == tool_calls

    def test_log_tool_result(self, logger):
        """log_tool_result should log tool execution results."""
        event = logger.log_tool_result(
            tool_call_id="call_123",
            name="read_file",
            content="def main():\n    print('hello')",
            status="ok",
            duration_ms=150.5
        )

        assert event.event == "tool_result"
        assert event.data["tool_call_id"] == "call_123"
        assert event.data["name"] == "read_file"
        assert event.data["status"] == "ok"
        assert event.data["duration_ms"] == 150.5

    def test_log_compaction(self, logger):
        """log_compaction should log compaction events."""
        event = logger.log_compaction(
            tokens_before=90000,
            tokens_after=60000,
            evicted_count=25,
            summary_tokens=2500,
            summary_preview="Goal: Implement feature X..."
        )

        assert event.event == "compaction"
        assert event.data["tokens_before"] == 90000
        assert event.data["tokens_after"] == 60000
        assert event.data["evicted_message_count"] == 25

    def test_log_error(self, logger):
        """log_error should log with error level."""
        event = logger.log_error(
            error_type="ValueError",
            message="Invalid argument"
        )

        assert event.event == "error"
        assert event.level == "error"
        assert event.data["error_type"] == "ValueError"


class TestTruncation:
    """Test content truncation for large outputs."""

    def test_small_content_not_truncated(self, logger):
        """Content under limit should not be truncated."""
        content = "x" * 1000
        event = logger.log("test", {"content": content})

        assert event.data["content"] == content
        assert "content_truncated" not in event.data

    def test_large_content_is_truncated(self, temp_dir):
        """Content over limit should be truncated."""
        logger = TranscriptLogger(
            session_id="test",
            base_dir=temp_dir,
            max_content_chars=100  # Low limit for testing
        )
        # Also set small head/tail for this test
        logger.HEAD_CHARS = 30
        logger.TAIL_CHARS = 20

        content = "x" * 200
        event = logger.log("test", {"content": content})

        assert len(event.data["content"]) < 200
        assert event.data["content_truncated"] is True
        assert event.data["content_original_len"] == 200
        assert "truncated" in event.data["content"]

    def test_truncation_preserves_head_and_tail(self, temp_dir):
        """Truncation should keep head and tail of content."""
        logger = TranscriptLogger(
            session_id="test",
            base_dir=temp_dir,
            max_content_chars=100
        )
        # Set small head/tail for testing
        logger.HEAD_CHARS = 20
        logger.TAIL_CHARS = 20

        content = "HEAD" + "x" * 100 + "TAIL"
        event = logger.log("test", {"content": content})

        truncated = event.data["content"]
        assert truncated.startswith("HEAD")
        assert truncated.endswith("TAIL")
        assert "truncated" in truncated


class TestSecretRedaction:
    """Test secret detection and redaction."""

    def test_api_key_redacted(self, logger):
        """API keys should be redacted."""
        event = logger.log("test", {
            "content": "Use this key: api_key=sk-1234567890abcdef1234567890"
        })

        assert "sk-1234567890" not in event.data["content"]
        assert "[REDACTED]" in event.data["content"]

    def test_password_redacted(self, logger):
        """Passwords should be redacted."""
        event = logger.log("test", {
            "content": "Login with password: mysecretpassword123"
        })

        assert "mysecretpassword123" not in event.data["content"]

    def test_sensitive_key_names_redacted(self, logger):
        """Values for sensitive key names should be redacted."""
        event = logger.log("test", {
            "password": "secret123",
            "api_key": "sk-abcdef",
            "normal_field": "visible"
        })

        assert event.data["password"] == "[REDACTED]"
        assert event.data["api_key"] == "[REDACTED]"
        assert event.data["normal_field"] == "visible"

    def test_redaction_can_be_disabled(self, temp_dir):
        """Redaction should be disableable."""
        logger = TranscriptLogger(
            session_id="test",
            base_dir=temp_dir,
            redact_secrets=False
        )

        event = logger.log("test", {
            "content": "api_key=sk-1234567890abcdef1234567890"
        })

        # With redaction disabled, the key should be visible
        assert "sk-1234567890" in event.data["content"]


class TestThreadSafety:
    """Test thread safety of logging."""

    def test_concurrent_logging(self, logger):
        """Concurrent logging should produce sequential events."""
        def log_event(i):
            return logger.log(f"event_{i}", {"index": i})

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(log_event, i) for i in range(100)]
            events = [f.result() for f in futures]

        # All sequence numbers should be unique
        seq_numbers = [e.seq for e in events]
        assert len(seq_numbers) == len(set(seq_numbers))

        # All events should be in file
        with open(logger.transcript_path, 'r') as f:
            lines = f.readlines()
        assert len(lines) == 100


class TestSequenceContinuity:
    """Test sequence number continuity across restarts."""

    def test_sequence_continues_on_resume(self, temp_dir):
        """Sequence should continue from last number on resume."""
        # First session
        logger1 = TranscriptLogger(session_id="test", base_dir=temp_dir)
        logger1.log("event1", {})
        logger1.log("event2", {})
        logger1.log("event3", {})

        # Resume session
        logger2 = TranscriptLogger(session_id="test", base_dir=temp_dir)
        event = logger2.log("event4", {})

        assert event.seq == 4


class TestQueryMethods:
    """Test transcript query functionality."""

    def test_get_events(self, logger):
        """get_events should return all events."""
        logger.log_user_message("Hello")
        logger.log_assistant_message("Hi there")
        logger.log_user_message("How are you?")

        events = logger.get_events()

        assert len(events) == 3
        assert events[0].event == "user_message"
        assert events[1].event == "assistant_message"
        assert events[2].event == "user_message"

    def test_get_events_with_filter(self, logger):
        """get_events should filter by event type."""
        logger.log_user_message("Hello")
        logger.log_assistant_message("Hi")
        logger.log_user_message("Bye")

        events = logger.get_events(event_types=["user_message"])

        assert len(events) == 2
        assert all(e.event == "user_message" for e in events)

    def test_get_events_with_since_seq(self, logger):
        """get_events should filter by sequence number."""
        logger.log("event1", {})
        logger.log("event2", {})
        logger.log("event3", {})

        events = logger.get_events(since_seq=1)

        assert len(events) == 2
        assert events[0].seq == 2
        assert events[1].seq == 3

    def test_get_events_with_limit(self, logger):
        """get_events should respect limit."""
        for i in range(10):
            logger.log(f"event_{i}", {})

        events = logger.get_events(limit=5)

        assert len(events) == 5

    def test_get_user_messages(self, logger):
        """get_user_messages should return only user message content."""
        logger.log_user_message("Hello")
        logger.log_assistant_message("Hi")
        logger.log_user_message("Bye")

        messages = logger.get_user_messages()

        assert messages == ["Hello", "Bye"]

    def test_get_stats(self, logger):
        """get_stats should return transcript statistics."""
        logger.log_user_message("Hello")
        logger.log_assistant_message("Hi")
        logger.log_tool_result("call_1", "read_file", "content")

        stats = logger.get_stats()

        assert stats["session_id"] == "test-session-123"
        assert stats["event_count"] == 3
        assert stats["events_by_type"]["user_message"] == 1
        assert stats["events_by_type"]["assistant_message"] == 1
        assert stats["events_by_type"]["tool_result"] == 1
        assert stats["file_size_bytes"] > 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_transcript_query(self, logger):
        """Querying empty transcript should return empty list."""
        events = logger.get_events()
        assert events == []

    def test_corrupted_line_skipped(self, logger):
        """Corrupted lines should be skipped during query."""
        # Write a valid event
        logger.log("event1", {"data": "valid"})

        # Manually append corrupted line
        with open(logger.transcript_path, 'a') as f:
            f.write("not valid json\n")

        # Write another valid event
        logger.log("event2", {"data": "also valid"})

        events = logger.get_events()

        # Should get both valid events, skipping corrupted
        assert len(events) == 2

    def test_nested_dict_sanitization(self, logger):
        """Nested dicts should also be sanitized."""
        event = logger.log("test", {
            "config": {
                "password": "secret",
                "normal": "value"
            }
        })

        assert event.data["config"]["password"] == "[REDACTED]"
        assert event.data["config"]["normal"] == "value"

    def test_list_sanitization(self, logger):
        """Lists should also be sanitized."""
        event = logger.log("test", {
            "items": [
                {"password": "secret1"},
                {"password": "secret2"}
            ]
        })

        assert event.data["items"][0]["password"] == "[REDACTED]"
        assert event.data["items"][1]["password"] == "[REDACTED]"


class TestTranscriptEvent:
    """Test TranscriptEvent dataclass."""

    def test_to_json(self):
        """to_json should produce valid JSON."""
        event = TranscriptEvent(
            v=1,
            session_id="test",
            seq=1,
            ts="2026-01-16T12:00:00.000Z",
            event="test_event",
            data={"key": "value"}
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["v"] == 1
        assert parsed["session_id"] == "test"
        assert parsed["seq"] == 1
        assert parsed["data"]["key"] == "value"

    def test_to_json_excludes_none(self):
        """to_json should exclude None values."""
        event = TranscriptEvent(
            v=1,
            session_id="test",
            seq=1,
            ts="2026-01-16T12:00:00.000Z",
            event="test_event",
            turn_id=None,  # Should be excluded
            data={}
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert "turn_id" not in parsed
