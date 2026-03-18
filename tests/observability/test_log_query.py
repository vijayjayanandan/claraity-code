"""
Test suite for src.observability.log_query (formatters, JSONL scanner, API).

Coverage:
- format_log: basic and verbose modes
- format_error: elapsed_ms display (regression test for the bug fix),
  None elapsed_ms safety
- scan_jsonl_files: session filter, level filter, text search,
  corrupted lines, rotated files
- _jsonl_to_log_record: JsonlEntry -> LogRecord conversion

Total: 11 tests

How to run:
    pytest tests/observability/test_log_query.py -v
"""

import json
from pathlib import Path

import pytest

from src.observability.error_store import ErrorRecord
from src.observability.log_store import LogRecord
from src.observability.log_query import (
    JsonlEntry,
    format_error,
    format_jsonl,
    format_log,
    scan_jsonl_files,
    _jsonl_to_log_record,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_log_record():
    """A typical LogRecord for formatter tests."""
    return LogRecord(
        id=1,
        ts="2026-01-15T14:30:45Z",
        level="INFO",
        event="tool_call_completed",
        logger="tools.file_ops",
        session_id="sess-fmt-001",
        component="tools.file_ops",
        operation="read_file",
        request_id="req-abc",
        source_file="file_operations.py",
        source_line=120,
        source_function="read_file",
        extra_json='{"duration_ms": 45, "bytes_read": 2048}',
    )


@pytest.fixture
def sample_error_record():
    """A typical ErrorRecord for formatter tests."""
    return ErrorRecord(
        id="err-001",
        ts="2026-01-15T14:35:00Z",
        level="ERROR",
        category="provider_timeout",
        error_type="TimeoutError",
        message="Connection timed out after 30s",
        session_id="sess-fmt-001",
        component="llm.openai",
        operation="chat_completion",
        model="gpt-4",
        backend="openai",
        elapsed_ms=3641.5,
        payload_bytes=4096,
        tool_name=None,
        tool_timeout_s=None,
        traceback="Traceback (most recent call last):\n  File ...\nTimeoutError",
    )


@pytest.fixture
def jsonl_dir(tmp_path):
    """
    Create a temporary log directory with JSONL files for scanner tests.

    Contains:
    - app.jsonl: 4 valid lines + 1 corrupted
    - app.jsonl.1: 2 valid lines (rotated)
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # Main file: 4 valid entries + 1 corrupted line
    entries = [
        {
            "event": "server_started",
            "level": "info",
            "timestamp": "2026-01-15T10:00:00Z",
            "session_id": "sess-111",
            "logger": "core.agent",
            "component": "core.agent",
        },
        {
            "event": "tool_call_begin",
            "level": "debug",
            "timestamp": "2026-01-15T10:01:00Z",
            "session_id": "sess-111",
            "logger": "tools.file_ops",
            "component": "tools.file_ops",
        },
        {
            "event": "provider_timeout",
            "level": "error",
            "timestamp": "2026-01-15T10:02:00Z",
            "session_id": "sess-222",
            "logger": "llm.backend",
            "component": "llm.backend",
        },
        {
            "event": "session_resumed",
            "level": "info",
            "timestamp": "2026-01-15T10:03:00Z",
            "session_id": "sess-111",
            "logger": "session.store",
            "component": "session.store",
        },
    ]
    lines = [json.dumps(e) for e in entries]
    lines.append("THIS IS NOT VALID JSON {{{")  # corrupted line
    (log_dir / "app.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    # Rotated file
    rotated_entries = [
        {
            "event": "old_startup",
            "level": "info",
            "timestamp": "2026-01-14T08:00:00Z",
            "session_id": "sess-000",
            "logger": "core.init",
        },
        {
            "event": "old_shutdown",
            "level": "warning",
            "timestamp": "2026-01-14T08:30:00Z",
            "session_id": "sess-000",
            "logger": "core.init",
        },
    ]
    rotated_lines = [json.dumps(e) for e in rotated_entries]
    (log_dir / "app.jsonl.1").write_text(
        "\n".join(rotated_lines) + "\n", encoding="utf-8"
    )

    return log_dir


# ---------------------------------------------------------------------------
# 1. format_log basic
# ---------------------------------------------------------------------------

class TestFormatLog:
    """Tests for format_log formatter."""

    def test_format_log_basic(self, sample_log_record):
        """Basic formatting includes level, timestamp, event, and context."""
        output = format_log(sample_log_record, verbose=False)

        # Header line
        assert "[INFO]" in output
        assert "2026-01-15 14:30:45" in output
        assert "tool_call_completed" in output

        # Logger
        assert "tools.file_ops" in output

        # Context parts
        assert "sess-fmt-001" in output
        assert "component=tools.file_ops" in output
        assert "op=read_file" in output

        # Source
        assert "file_operations.py:120" in output
        assert "read_file" in output

        # Extra JSON should NOT appear in non-verbose mode
        assert "duration_ms" not in output
        assert "bytes_read" not in output

    def test_format_log_verbose(self, sample_log_record):
        """Verbose mode includes extra_json key-value pairs."""
        output = format_log(sample_log_record, verbose=True)

        # Extra JSON fields should appear
        assert "duration_ms" in output
        assert "45" in output
        assert "bytes_read" in output
        assert "2048" in output


# ---------------------------------------------------------------------------
# 2-3. format_error (elapsed_ms regression + None safety)
# ---------------------------------------------------------------------------

class TestFormatError:
    """Tests for format_error formatter, especially elapsed_ms display."""

    def test_format_error_elapsed_ms(self, sample_error_record):
        """
        CRITICAL regression test: verify elapsed_ms displays correctly.

        This was a bug fix -- the old code used error.elapsed_s (which
        did not exist), causing an AttributeError.  The fix changed it
        to error.elapsed_ms.
        """
        output = format_error(sample_error_record, verbose=False)

        # Must show the elapsed time in milliseconds
        # 3641.5 formatted with :.0f gives "3642" (rounded)
        assert "3642ms" in output or "3641ms" in output

        # Also verify other fields render
        assert "[ERROR]" in output
        assert "provider_timeout" in output
        assert "TimeoutError" in output
        assert "Connection timed out" in output
        assert "model=gpt-4" in output
        assert "backend=openai" in output
        assert "payload=4096B" in output

    def test_format_error_no_elapsed(self):
        """No crash when elapsed_ms is None."""
        error = ErrorRecord(
            id="err-no-elapsed",
            ts="2026-01-15T15:00:00Z",
            level="ERROR",
            category="tool_error",
            error_type="RuntimeError",
            message="Tool failed",
            elapsed_ms=None,
        )
        output = format_error(error, verbose=False)

        # Should render without crashing
        assert "[ERROR]" in output
        assert "tool_error" in output
        assert "Tool failed" in output
        # "Elapsed" line should be absent when elapsed_ms is None
        assert "Elapsed" not in output

    def test_format_error_verbose_traceback(self, sample_error_record):
        """Verbose mode shows the traceback."""
        output = format_error(sample_error_record, verbose=True)
        assert "Traceback" in output
        assert "TimeoutError" in output


# ---------------------------------------------------------------------------
# 4-8. scan_jsonl_files
# ---------------------------------------------------------------------------

class TestScanJsonlFiles:
    """Tests for JSONL file scanner."""

    def test_scan_jsonl_files(self, jsonl_dir):
        """Scans JSONL files and returns JsonlEntry objects."""
        results = scan_jsonl_files(log_dir=str(jsonl_dir), limit=100)

        # 4 from app.jsonl + 2 from app.jsonl.1 = 6
        # (corrupted line is skipped)
        assert len(results) == 6
        assert all(isinstance(r, JsonlEntry) for r in results)

    def test_scan_jsonl_session_filter(self, jsonl_dir):
        """Pre-filter by session_id (fast string match)."""
        results = scan_jsonl_files(
            log_dir=str(jsonl_dir),
            session_id="sess-111",
            limit=100,
        )

        assert len(results) == 3
        assert all(r.session_id == "sess-111" for r in results)

    def test_scan_jsonl_level_filter(self, jsonl_dir):
        """Filter by level (case-insensitive)."""
        results = scan_jsonl_files(
            log_dir=str(jsonl_dir),
            level="error",
            limit=100,
        )

        assert len(results) == 1
        assert results[0].event == "provider_timeout"

    def test_scan_jsonl_text_search(self, jsonl_dir):
        """Full-text search across the entire JSON line."""
        results = scan_jsonl_files(
            log_dir=str(jsonl_dir),
            text="timeout",
            limit=100,
        )

        assert len(results) == 1
        assert results[0].event == "provider_timeout"

    def test_scan_jsonl_corrupted_lines(self, jsonl_dir):
        """Corrupted JSON lines are gracefully skipped (not crashing)."""
        # The jsonl_dir fixture includes one corrupted line.
        # If scanning crashed on bad JSON, this call would raise.
        results = scan_jsonl_files(log_dir=str(jsonl_dir), limit=100)

        # 6 valid entries total (4 main + 2 rotated)
        assert len(results) == 6

    def test_scan_jsonl_rotated_files(self, jsonl_dir):
        """Scanner reads both app.jsonl and app.jsonl.1 (rotated)."""
        results = scan_jsonl_files(
            log_dir=str(jsonl_dir),
            session_id="sess-000",
            limit=100,
        )

        # sess-000 only exists in app.jsonl.1
        assert len(results) == 2
        events = {r.event for r in results}
        assert "old_startup" in events
        assert "old_shutdown" in events

    def test_scan_jsonl_ordering(self, jsonl_dir):
        """Results are sorted by timestamp descending."""
        results = scan_jsonl_files(log_dir=str(jsonl_dir), limit=100)
        timestamps = [r.ts for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# 9. _jsonl_to_log_record
# ---------------------------------------------------------------------------

class TestJsonlToLogRecord:
    """Tests for JsonlEntry -> LogRecord conversion."""

    def test_jsonl_to_log_record(self):
        """JsonlEntry correctly converts to a LogRecord with all fields."""
        raw = {
            "event": "test_event",
            "level": "INFO",
            "logger": "test.logger",
            "timestamp": "2026-01-15T10:00:00Z",
            "session_id": "sess-conv",
            "run_id": "run-conv",
            "stream_id": "strm-conv",
            "request_id": "req-conv",
            "component": "test.comp",
            "operation": "do_thing",
            "source": {
                "file": "my_file.py",
                "line": 55,
                "function": "do_thing",
            },
            "custom_key": "custom_value",
        }

        entry = JsonlEntry(
            ts="2026-01-15T10:00:00Z",
            level="INFO",
            event="test_event",
            logger="test.logger",
            session_id="sess-conv",
            component="test.comp",
            raw=raw,
        )

        record = _jsonl_to_log_record(entry)

        assert isinstance(record, LogRecord)
        assert record.id is None
        assert record.ts == "2026-01-15T10:00:00Z"
        assert record.level == "INFO"
        assert record.event == "test_event"
        assert record.logger == "test.logger"
        assert record.session_id == "sess-conv"
        assert record.run_id == "run-conv"
        assert record.request_id == "req-conv"
        assert record.component == "test.comp"
        assert record.operation == "do_thing"
        assert record.source_file == "my_file.py"
        assert record.source_line == 55
        assert record.source_function == "do_thing"

        # custom_key should end up in extra_json
        assert record.extra_json is not None
        extras = json.loads(record.extra_json)
        assert extras["custom_key"] == "custom_value"

    def test_jsonl_to_log_record_flat_source(self):
        """Falls back to flat filename/lineno/func_name if nested source absent."""
        raw = {
            "event": "flat_source",
            "level": "DEBUG",
            "logger": "test",
            "timestamp": "2026-01-15T11:00:00Z",
            "filename": "flat_file.py",
            "lineno": 77,
            "func_name": "flat_func",
        }

        entry = JsonlEntry(
            ts="2026-01-15T11:00:00Z",
            level="DEBUG",
            event="flat_source",
            logger="test",
            raw=raw,
        )

        record = _jsonl_to_log_record(entry)

        assert record.source_file == "flat_file.py"
        assert record.source_line == 77
        assert record.source_function == "flat_func"
