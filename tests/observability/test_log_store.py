"""
Test suite for src.observability.log_store (LogStore and LogRecord).

Coverage:
- LogRecord: dataclass construction and to_dict serialization
- LogStore.__init__: DB creation, schema, indexes
- LogStore.record / record_from_dict: single-record insert and retrieval
- LogStore.record_batch: batch insert (empty and populated)
- LogStore.query: filtering by session_id, level, component, event, text,
  since_minutes, limit, and ordering
- LogStore.count_by_level: group counts
- LogStore.clear_old: time-based cleanup
- LogStore.get_db_size_bytes: file size reporting
- Truncation: event and extra_json length limits

Total: 19 tests

How to run:
    pytest tests/observability/test_log_store.py -v
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from src.observability.log_store import (
    LogRecord,
    LogStore,
    MAX_EVENT_LENGTH,
    MAX_EXTRA_JSON_LENGTH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Create an isolated LogStore backed by a temp directory DB."""
    db_path = str(tmp_path / "test_logs.db")
    return LogStore(db_path=db_path)


@pytest.fixture
def populated_store(store):
    """
    LogStore pre-loaded with a handful of records for query tests.

    Records span two sessions and multiple log levels.
    """
    base_ts = "2026-01-15T10:00:00Z"

    records = [
        {
            "level": "INFO",
            "event": "server_started",
            "ts": "2026-01-15T10:00:00Z",
            "session_id": "sess-aaa",
            "component": "core.agent",
            "logger": "core.agent",
        },
        {
            "level": "DEBUG",
            "event": "tool_call_begin",
            "ts": "2026-01-15T10:01:00Z",
            "session_id": "sess-aaa",
            "component": "tools.file_ops",
            "logger": "tools.file_ops",
        },
        {
            "level": "WARNING",
            "event": "token_budget_low",
            "ts": "2026-01-15T10:02:00Z",
            "session_id": "sess-bbb",
            "component": "llm.backend",
            "logger": "llm.backend",
        },
        {
            "level": "ERROR",
            "event": "provider_timeout",
            "ts": "2026-01-15T10:03:00Z",
            "session_id": "sess-bbb",
            "component": "llm.backend",
            "logger": "llm.backend",
            "retry_count": 3,  # extra field -> extra_json
        },
        {
            "level": "INFO",
            "event": "session_resumed",
            "ts": "2026-01-15T10:04:00Z",
            "session_id": "sess-aaa",
            "component": "session.store",
            "logger": "session.store",
        },
    ]

    store.record_batch([r.copy() for r in records])
    return store


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------

class TestLogStoreInit:
    """Tests for LogStore database initialization."""

    def test_init_creates_db(self, tmp_path):
        """LogStore creates the DB file and the logs table on init."""
        db_path = str(tmp_path / "sub" / "logs.db")
        s = LogStore(db_path=db_path)

        # File exists
        assert s.db_path.exists()

        # Table exists with expected columns
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(logs)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id", "ts", "level", "event", "logger",
            "run_id", "session_id", "stream_id", "request_id",
            "component", "operation",
            "source_file", "source_line", "source_function",
            "extra_json",
        }
        assert expected.issubset(columns)


# ---------------------------------------------------------------------------
# 2-3. record_from_dict (basic and extras)
# ---------------------------------------------------------------------------

class TestRecordFromDict:
    """Tests for LogStore.record_from_dict convenience method."""

    def test_record_from_dict(self, store):
        """Insert via record_from_dict and retrieve the record."""
        row_id = store.record_from_dict(
            level="INFO",
            event="test_event",
            session_id="sess-123",
            component="test.module",
            logger="test.logger",
        )

        assert row_id > 0

        results = store.query(session_id="sess-123")
        assert len(results) == 1
        rec = results[0]
        assert rec.level == "INFO"
        assert rec.event == "test_event"
        assert rec.session_id == "sess-123"
        assert rec.component == "test.module"
        assert rec.logger == "test.logger"

    def test_record_from_dict_with_extras(self, store):
        """Unknown keyword args are serialized into extra_json."""
        row_id = store.record_from_dict(
            level="WARNING",
            event="custom_event",
            custom_field="hello",
            numeric_extra=42,
        )

        assert row_id > 0

        results = store.query(event="custom_event")
        assert len(results) == 1
        rec = results[0]
        assert rec.extra_json is not None

        extras = json.loads(rec.extra_json)
        assert extras["custom_field"] == "hello"
        assert extras["numeric_extra"] == 42


# ---------------------------------------------------------------------------
# 4-5. record_batch
# ---------------------------------------------------------------------------

class TestRecordBatch:
    """Tests for LogStore.record_batch bulk insertion."""

    def test_record_batch(self, store):
        """Batch insert multiple records in a single transaction."""
        records = [
            {"level": "INFO", "event": f"event_{i}", "session_id": "sess-batch"}
            for i in range(5)
        ]

        inserted = store.record_batch([r.copy() for r in records])
        assert inserted == 5

        results = store.query(session_id="sess-batch")
        assert len(results) == 5

    def test_record_batch_empty(self, store):
        """Empty batch returns 0 without touching DB."""
        inserted = store.record_batch([])
        assert inserted == 0


# ---------------------------------------------------------------------------
# 6-12. query filters
# ---------------------------------------------------------------------------

class TestQuery:
    """Tests for LogStore.query filtering and ordering."""

    def test_query_by_session_id(self, populated_store):
        """Filter by exact session_id match."""
        results = populated_store.query(session_id="sess-aaa")
        assert len(results) == 3
        assert all(r.session_id == "sess-aaa" for r in results)

    def test_query_by_level(self, populated_store):
        """Filter by level (case-insensitive)."""
        results = populated_store.query(level="error")
        assert len(results) == 1
        assert results[0].event == "provider_timeout"

        # Uppercase should also work
        results_upper = populated_store.query(level="ERROR")
        assert len(results_upper) == 1
        assert results_upper[0].event == "provider_timeout"

    def test_query_by_component(self, populated_store):
        """Filter by component (substring match on component or logger)."""
        results = populated_store.query(component="llm")
        assert len(results) == 2
        events = {r.event for r in results}
        assert "token_budget_low" in events
        assert "provider_timeout" in events

    def test_query_by_event(self, populated_store):
        """Filter by event name (substring match)."""
        results = populated_store.query(event="timeout")
        assert len(results) == 1
        assert results[0].event == "provider_timeout"

    def test_query_by_text(self, populated_store):
        """Full-text search across event and extra_json."""
        # Search in event text
        results = populated_store.query(text="server_started")
        assert len(results) == 1
        assert results[0].event == "server_started"

        # Search in extra_json (retry_count was stored there)
        results = populated_store.query(text="retry_count")
        assert len(results) == 1
        assert results[0].event == "provider_timeout"

    def test_query_since_minutes(self, store):
        """Time-based filtering returns only recent records."""
        now = datetime.utcnow()
        recent_ts = (now - timedelta(minutes=5)).isoformat() + "Z"
        old_ts = (now - timedelta(minutes=120)).isoformat() + "Z"

        store.record_from_dict(
            level="INFO", event="recent_event", ts=recent_ts
        )
        store.record_from_dict(
            level="INFO", event="old_event", ts=old_ts
        )

        results = store.query(since_minutes=30)
        assert len(results) == 1
        assert results[0].event == "recent_event"

    def test_query_limit(self, populated_store):
        """Respects limit parameter."""
        results = populated_store.query(limit=2)
        assert len(results) == 2

    def test_query_order(self, populated_store):
        """Results are ordered by ts DESC (most recent first)."""
        results = populated_store.query(limit=100)
        timestamps = [r.ts for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# 13. count_by_level
# ---------------------------------------------------------------------------

class TestCountByLevel:
    """Tests for LogStore.count_by_level aggregation."""

    def test_count_by_level(self, populated_store):
        """Group counts by log level."""
        counts = populated_store.count_by_level()

        assert counts.get("INFO") == 2
        assert counts.get("DEBUG") == 1
        assert counts.get("WARNING") == 1
        assert counts.get("ERROR") == 1


# ---------------------------------------------------------------------------
# 14. clear_old
# ---------------------------------------------------------------------------

class TestClearOld:
    """Tests for LogStore.clear_old retention cleanup."""

    def test_clear_old(self, store):
        """Delete records older than N days."""
        now = datetime.utcnow()
        old_ts = (now - timedelta(days=10)).isoformat() + "Z"
        recent_ts = (now - timedelta(hours=1)).isoformat() + "Z"

        store.record_from_dict(level="INFO", event="old", ts=old_ts)
        store.record_from_dict(level="INFO", event="recent", ts=recent_ts)

        deleted = store.clear_old(days=7)
        assert deleted == 1

        remaining = store.query(limit=100)
        assert len(remaining) == 1
        assert remaining[0].event == "recent"


# ---------------------------------------------------------------------------
# 15. get_db_size_bytes
# ---------------------------------------------------------------------------

class TestGetDbSizeBytes:
    """Tests for LogStore.get_db_size_bytes file-size reporting."""

    def test_get_db_size_bytes(self, store):
        """Returns a positive integer for a non-empty database."""
        store.record_from_dict(level="INFO", event="size_test")
        size = store.get_db_size_bytes()
        assert isinstance(size, int)
        assert size > 0


# ---------------------------------------------------------------------------
# 16-17. Truncation
# ---------------------------------------------------------------------------

class TestTruncation:
    """Tests for event and extra_json truncation limits."""

    def test_event_truncation(self, store):
        """Events longer than MAX_EVENT_LENGTH are truncated."""
        long_event = "x" * (MAX_EVENT_LENGTH + 500)
        store.record_from_dict(level="INFO", event=long_event)

        results = store.query(limit=1)
        assert len(results) == 1
        stored_event = results[0].event
        assert len(stored_event) <= MAX_EVENT_LENGTH + len("...[truncated]")
        assert stored_event.endswith("...[truncated]")

    def test_extra_json_truncation(self, store):
        """Extra JSON longer than MAX_EXTRA_JSON_LENGTH is truncated."""
        big_value = "y" * (MAX_EXTRA_JSON_LENGTH + 500)
        store.record_from_dict(
            level="INFO",
            event="extra_test",
            huge_field=big_value,
        )

        results = store.query(event="extra_test")
        assert len(results) == 1
        extra = results[0].extra_json
        assert extra is not None
        assert len(extra) <= MAX_EXTRA_JSON_LENGTH + len("...[truncated]")
        assert extra.endswith("...[truncated]")


# ---------------------------------------------------------------------------
# 18. to_dict
# ---------------------------------------------------------------------------

class TestLogRecordToDict:
    """Tests for LogRecord.to_dict() serialization."""

    def test_to_dict(self):
        """to_dict returns a dict with all fields."""
        rec = LogRecord(
            id=1,
            ts="2026-01-15T10:00:00Z",
            level="INFO",
            event="test_event",
            logger="test.logger",
            session_id="sess-abc",
            component="core.agent",
            source_file="agent.py",
            source_line=42,
            source_function="run",
            extra_json='{"key": "value"}',
        )

        d = rec.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == 1
        assert d["ts"] == "2026-01-15T10:00:00Z"
        assert d["level"] == "INFO"
        assert d["event"] == "test_event"
        assert d["logger"] == "test.logger"
        assert d["session_id"] == "sess-abc"
        assert d["component"] == "core.agent"
        assert d["source_file"] == "agent.py"
        assert d["source_line"] == 42
        assert d["source_function"] == "run"
        assert d["extra_json"] == '{"key": "value"}'
        # Optional fields default to None
        assert d["run_id"] is None
        assert d["stream_id"] is None
        assert d["request_id"] is None
        assert d["operation"] is None
