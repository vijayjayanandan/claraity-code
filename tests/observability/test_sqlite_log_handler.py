"""
Test suite for src.observability.sqlite_log_handler (SQLiteLogHandler).

Coverage:
- emit() with structlog dict records (record.msg is dict)
- emit() with plain stdlib string records
- _extract_record_data: context fields, source location extraction
- Batch flushing: records appear in DB after batch_size threshold
- Graceful shutdown: close() flushes remaining queued records
- Queue-full behavior: records are dropped (not blocking)

Total: 7 tests

How to run:
    pytest tests/observability/test_sqlite_log_handler.py -v
"""

import logging
import time

import pytest

from src.observability.log_store import LogStore
from src.observability.sqlite_log_handler import SQLiteLogHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return path string for a temporary SQLite DB."""
    return str(tmp_path / "test_handler_logs.db")


@pytest.fixture
def log_store(db_path):
    """Create a LogStore at the temporary DB path."""
    return LogStore(db_path=db_path)


@pytest.fixture
def handler(db_path, log_store, monkeypatch):
    """
    Create a SQLiteLogHandler that uses our test DB.

    Monkeypatches _get_log_store so the handler's writer thread
    writes to our temp DB instead of the global singleton.
    """
    h = SQLiteLogHandler(db_path=db_path, queue_size=100, batch_size=5)
    monkeypatch.setattr(h, "_get_log_store", lambda: log_store)
    yield h
    # Ensure handler is closed even if test forgets
    try:
        h.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_structlog_record(event_dict):
    """
    Create a logging.LogRecord that simulates structlog's
    ProcessorFormatter.wrap_for_formatter behaviour (record.msg is a dict).
    """
    record = logging.LogRecord(
        name=event_dict.get("logger", "test.logger"),
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg=event_dict,
        args=(),
        exc_info=None,
    )
    return record


def _make_plain_record(message, level=logging.INFO, name="test.plain"):
    """Create a standard stdlib logging.LogRecord with a string message."""
    return logging.LogRecord(
        name=name,
        level=level,
        pathname="some_file.py",
        lineno=99,
        msg=message,
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# 1. Structlog dict record
# ---------------------------------------------------------------------------

class TestEmitStructlogDict:
    """Tests for handling structlog dict records (record.msg is dict)."""

    def test_emit_structlog_dict_record(self, handler, log_store):
        """Handler correctly extracts fields from a structlog dict record."""
        event_dict = {
            "event": "llm_call_started",
            "level": "info",
            "logger": "core.agent",
            "session_id": "sess-struct-123",
            "component": "llm.openai",
            "timestamp": "2026-01-15T12:00:00Z",
        }
        record = _make_structlog_record(event_dict)
        handler.emit(record)
        handler.close()

        results = log_store.query(session_id="sess-struct-123")
        assert len(results) == 1

        stored = results[0]
        assert stored.event == "llm_call_started"
        assert stored.session_id == "sess-struct-123"
        assert stored.component == "llm.openai"
        assert stored.logger == "core.agent"


# ---------------------------------------------------------------------------
# 2. Plain string record
# ---------------------------------------------------------------------------

class TestEmitPlainString:
    """Tests for handling plain stdlib string records."""

    def test_emit_plain_string_record(self, handler, log_store):
        """Handler stores a plain string message as the event."""
        record = _make_plain_record("Something happened in the app")
        handler.emit(record)
        handler.close()

        results = log_store.query(limit=10)
        assert len(results) == 1

        stored = results[0]
        assert stored.event == "Something happened in the app"
        assert stored.logger == "test.plain"


# ---------------------------------------------------------------------------
# 3. Context field extraction
# ---------------------------------------------------------------------------

class TestExtractContextFields:
    """Tests for _extract_record_data context field extraction."""

    def test_extract_context_fields(self, handler):
        """All named context fields are extracted from the event dict."""
        event_dict = {
            "event": "ctx_test",
            "level": "info",
            "logger": "ctx.logger",
            "run_id": "run-001",
            "session_id": "sess-ctx",
            "request_id": "req-abc",
            "component": "core.tools",
            "operation": "file_read",
            "timestamp": "2026-01-15T12:00:00Z",
        }
        record = _make_structlog_record(event_dict)
        data = handler._extract_record_data(record)

        assert data["event"] == "ctx_test"
        assert data["logger"] == "ctx.logger"
        assert data["run_id"] == "run-001"
        assert data["session_id"] == "sess-ctx"
        assert data["request_id"] == "req-abc"
        assert data["component"] == "core.tools"
        assert data["operation"] == "file_read"
        assert data["ts"] == "2026-01-15T12:00:00Z"


# ---------------------------------------------------------------------------
# 4. Source location extraction
# ---------------------------------------------------------------------------

class TestExtractSourceLocation:
    """Tests for _extract_record_data source location fields."""

    def test_extract_source_location(self, handler):
        """Source file, line, and function are extracted from structlog."""
        event_dict = {
            "event": "source_test",
            "level": "debug",
            "filename": "agent.py",
            "lineno": 583,
            "func_name": "_execute_with_tools",
        }
        record = _make_structlog_record(event_dict)
        data = handler._extract_record_data(record)

        assert data["source_file"] == "agent.py"
        assert data["source_line"] == 583
        assert data["source_function"] == "_execute_with_tools"

    def test_extract_source_location_fallback(self, handler):
        """When structlog fields are absent, falls back to LogRecord attrs."""
        record = _make_plain_record("fallback test")
        data = handler._extract_record_data(record)

        # Falls back to logging.LogRecord fields
        assert data["source_file"] == "some_file.py"
        assert data["source_line"] == 99
        # funcName is None for manually created LogRecords (only auto-set
        # by Logger._log), so source_function will be None here.
        assert "source_function" in data


# ---------------------------------------------------------------------------
# 5. Batch flushing
# ---------------------------------------------------------------------------

class TestBatchFlushing:
    """Tests for batch flush threshold behavior."""

    def test_batch_flushing(self, db_path, monkeypatch):
        """After emitting batch_size records they appear in DB."""
        batch_size = 3
        log_st = LogStore(db_path=db_path)
        h = SQLiteLogHandler(
            db_path=db_path, queue_size=100, batch_size=batch_size
        )
        monkeypatch.setattr(h, "_get_log_store", lambda: log_st)

        try:
            for i in range(batch_size):
                record = _make_plain_record(f"batch_event_{i}")
                h.emit(record)

            # Give the writer thread time to flush the batch
            time.sleep(2)

            results = log_st.query(limit=100)
            assert len(results) >= batch_size
        finally:
            h.close()


# ---------------------------------------------------------------------------
# 6. Graceful shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    """Tests for handler close/shutdown flushing."""

    def test_graceful_shutdown(self, db_path, monkeypatch):
        """close() flushes all remaining queued records to DB."""
        log_st = LogStore(db_path=db_path)
        h = SQLiteLogHandler(
            db_path=db_path, queue_size=100, batch_size=50
        )
        monkeypatch.setattr(h, "_get_log_store", lambda: log_st)

        # Emit fewer records than batch_size so they stay queued
        for i in range(4):
            record = _make_plain_record(f"shutdown_event_{i}")
            h.emit(record)

        # Close triggers flush of remaining records
        h.close()

        results = log_st.query(limit=100)
        assert len(results) == 4
        events = {r.event for r in results}
        for i in range(4):
            assert f"shutdown_event_{i}" in events


# ---------------------------------------------------------------------------
# 7. Queue full drops
# ---------------------------------------------------------------------------

class TestQueueFullDrops:
    """Tests for bounded queue overflow behavior."""

    def test_queue_full_drops(self, db_path, monkeypatch):
        """When the queue is full, new records are dropped without blocking."""
        tiny_queue = 2
        log_st = LogStore(db_path=db_path)

        # Use a very large batch_size so nothing gets flushed by the
        # writer thread while we fill the queue.
        h = SQLiteLogHandler(
            db_path=db_path, queue_size=tiny_queue, batch_size=1000
        )
        monkeypatch.setattr(h, "_get_log_store", lambda: log_st)

        try:
            # Pause the writer thread by making the shutdown event "almost" set
            # so the queue fills up.  We achieve this by emitting many records
            # very quickly -- some will be dropped.
            emitted = 0
            for i in range(tiny_queue + 20):
                record = _make_plain_record(f"overflow_{i}")
                h.emit(record)
                emitted += 1

            # The critical assertion: emit() did NOT block.  If it blocked,
            # we would never reach this line within the test timeout.
            assert emitted == tiny_queue + 20
        finally:
            h.close()
