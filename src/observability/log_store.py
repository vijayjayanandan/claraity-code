"""
SQLite log store for queryable persistence of ALL log levels.

Complements the ErrorStore (metrics.db, errors only) by providing
SQL-queryable access to every log record the application produces.

Schema designed for fast queries on:
- session_id (correlation)
- level (severity filtering)
- ts (time-based queries)
- event (event name filtering)
- component (source filtering)

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Thread-safe with RLock
- WAL mode for concurrent read/write
- Auto-cleanup of old logs (7-day default retention)
- Batch insert support for high-throughput writing
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# =============================================================================
# CONSTANTS
# =============================================================================

# Default database path (grouped with JSONL files in logs directory)
DEFAULT_LOG_DB_PATH = ".claraity/logs/logs.db"

# Default retention period (shorter than errors' 30 days due to higher volume)
DEFAULT_LOG_RETENTION_DAYS = 7

# Default query limit
DEFAULT_LOG_QUERY_LIMIT = 100

# Truncation limits to prevent DB bloat
MAX_EVENT_LENGTH = 8192
MAX_EXTRA_JSON_LENGTH = 16384


# =============================================================================
# DATA MODEL
# =============================================================================


@dataclass
class LogRecord:
    """Structured log record for storage and queries."""

    id: int | None  # AUTOINCREMENT, assigned by SQLite (None on insert)
    ts: str
    level: str
    event: str
    logger: str | None = None
    # Context
    run_id: str | None = None
    session_id: str | None = None
    stream_id: str | None = None
    request_id: str | None = None
    component: str | None = None
    operation: str | None = None
    # Source location
    source_file: str | None = None
    source_line: int | None = None
    source_function: str | None = None
    # Extra data as JSON (everything that doesn't fit named columns)
    extra_json: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# =============================================================================
# LOG STORE
# =============================================================================


class LogStore:
    """
    SQLite-based log storage for queryable persistence of ALL log levels.

    Features:
    - Thread-safe operations via RLock
    - WAL mode for concurrent read/write performance
    - Batch insert for high-throughput writing
    - Time-based cleanup
    - Indexed queries by session, level, event, component, time
    """

    def __init__(self, db_path: str = DEFAULT_LOG_DB_PATH):
        """
        Initialize log store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _get_connection(self):
        """Thread-safe context manager for database connections."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _init_schema(self):
        """Initialize database schema with WAL mode and indexes."""
        with self._get_connection() as conn:
            # Enable WAL mode for concurrent read/write performance
            conn.execute("PRAGMA journal_mode=WAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    event TEXT NOT NULL,
                    logger TEXT,
                    run_id TEXT,
                    session_id TEXT,
                    stream_id TEXT,
                    request_id TEXT,
                    component TEXT,
                    operation TEXT,
                    source_file TEXT,
                    source_line INTEGER,
                    source_function TEXT,
                    extra_json TEXT
                )
            """)

            # Create indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_event ON logs(event)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_component ON logs(component)")

            conn.commit()

    def record(self, log: LogRecord) -> int:
        """
        Record a single log entry.

        Args:
            log: LogRecord to store

        Returns:
            Row ID of inserted record
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO logs (
                        ts, level, event, logger,
                        run_id, session_id, stream_id, request_id,
                        component, operation,
                        source_file, source_line, source_function,
                        extra_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        log.ts,
                        log.level,
                        log.event,
                        log.logger,
                        log.run_id,
                        log.session_id,
                        log.stream_id,
                        log.request_id,
                        log.component,
                        log.operation,
                        log.source_file,
                        log.source_line,
                        log.source_function,
                        log.extra_json,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            # Use stderr to avoid recursion (this module is used by logging)
            import sys

            try:
                print(f"[LogStore] Failed to record log: {e}", file=sys.__stderr__)
            except Exception:
                pass
            return -1

    def record_from_dict(self, level: str, event: str, **kwargs) -> int:
        """
        Record a log entry from individual fields.

        Known fields go to named columns; unknown fields go to extra_json.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            event: Event name
            **kwargs: Additional fields

        Returns:
            Row ID of inserted record
        """
        ts = kwargs.pop("ts", None) or (datetime.utcnow().isoformat() + "Z")

        # Truncate event to prevent DB bloat
        if len(event) > MAX_EVENT_LENGTH:
            event = event[:MAX_EVENT_LENGTH] + "...[truncated]"

        # Separate known fields from extras
        known_fields = {
            "logger",
            "run_id",
            "session_id",
            "stream_id",
            "request_id",
            "component",
            "operation",
            "source_file",
            "source_line",
            "source_function",
        }
        record_kwargs = {}
        extra_fields = {}

        for key, value in kwargs.items():
            if key in known_fields:
                record_kwargs[key] = value
            else:
                extra_fields[key] = value

        # Serialize extra fields
        extra_json = None
        if extra_fields:
            try:
                raw = json.dumps(extra_fields, default=str)
                if len(raw) > MAX_EXTRA_JSON_LENGTH:
                    raw = raw[:MAX_EXTRA_JSON_LENGTH] + "...[truncated]"
                extra_json = raw
            except (TypeError, ValueError):
                extra_json = json.dumps(
                    {"_serialization_error": str(extra_fields)[:500]}, default=str
                )

        log = LogRecord(
            id=None,
            ts=ts,
            level=level,
            event=event,
            extra_json=extra_json,
            **record_kwargs,
        )
        return self.record(log)

    def record_batch(self, records: list[dict[str, Any]]) -> int:
        """
        Insert multiple log records in a single transaction.

        Args:
            records: list of dicts with fields for record_from_dict()

        Returns:
            Number of records inserted
        """
        if not records:
            return 0

        try:
            with self._get_connection() as conn:
                inserted = 0
                # Fields extracted separately (not stored as extras)
                skip_fields = {"level", "event", "ts"}
                known_fields = {
                    "logger",
                    "run_id",
                    "session_id",
                    "stream_id",
                    "request_id",
                    "component",
                    "operation",
                    "source_file",
                    "source_line",
                    "source_function",
                }

                for rec in records:
                    # Use .get() to avoid mutating input dicts
                    level = rec.get("level", "INFO")
                    event = rec.get("event", "")
                    ts = rec.get("ts") or (datetime.utcnow().isoformat() + "Z")

                    # Truncate
                    if len(event) > MAX_EVENT_LENGTH:
                        event = event[:MAX_EVENT_LENGTH] + "...[truncated]"

                    # Separate known from extras
                    named = {}
                    extras = {}
                    for key, value in rec.items():
                        if key in skip_fields:
                            continue
                        elif key in known_fields:
                            named[key] = value
                        else:
                            extras[key] = value

                    extra_json = None
                    if extras:
                        try:
                            raw = json.dumps(extras, default=str)
                            if len(raw) > MAX_EXTRA_JSON_LENGTH:
                                raw = raw[:MAX_EXTRA_JSON_LENGTH] + "...[truncated]"
                            extra_json = raw
                        except (TypeError, ValueError):
                            extra_json = None

                    conn.execute(
                        """
                        INSERT INTO logs (
                            ts, level, event, logger,
                            run_id, session_id, stream_id, request_id,
                            component, operation,
                            source_file, source_line, source_function,
                            extra_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            ts,
                            level,
                            event,
                            named.get("logger"),
                            named.get("run_id"),
                            named.get("session_id"),
                            named.get("stream_id"),
                            named.get("request_id"),
                            named.get("component"),
                            named.get("operation"),
                            named.get("source_file"),
                            named.get("source_line"),
                            named.get("source_function"),
                            extra_json,
                        ),
                    )
                    inserted += 1

                conn.commit()
                return inserted
        except Exception as e:
            import sys

            try:
                print(f"[LogStore] Failed to record batch: {e}", file=sys.__stderr__)
            except Exception:
                pass
            return 0

    def _row_to_record(self, row: sqlite3.Row) -> LogRecord:
        """Convert a database row to a LogRecord."""
        data = dict(row)
        valid_fields = {f.name for f in dataclass_fields(LogRecord)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return LogRecord(**filtered)

    def query(
        self,
        session_id: str | None = None,
        level: str | None = None,
        component: str | None = None,
        event: str | None = None,
        text: str | None = None,
        since_minutes: int | None = None,
        limit: int = DEFAULT_LOG_QUERY_LIMIT,
    ) -> list[LogRecord]:
        """
        Query logs with filters.

        Args:
            session_id: Filter by session ID (exact match)
            level: Filter by log level (exact match, case-insensitive)
            component: Filter by component (substring match)
            event: Filter by event name (substring match)
            text: Full-text search in event and extra_json
            since_minutes: Filter to last N minutes
            limit: Maximum results

        Returns:
            list of LogRecord
        """
        try:
            with self._get_connection() as conn:
                sql = "SELECT * FROM logs WHERE 1=1"
                params = []

                if session_id:
                    sql += " AND session_id = ?"
                    params.append(session_id)

                if level:
                    sql += " AND UPPER(level) = ?"
                    params.append(level.upper())

                if component:
                    sql += " AND (component LIKE ? OR logger LIKE ?)"
                    pattern = f"%{component}%"
                    params.extend([pattern, pattern])

                if event:
                    sql += " AND event LIKE ?"
                    params.append(f"%{event}%")

                if text:
                    sql += " AND (event LIKE ? OR extra_json LIKE ?)"
                    pattern = f"%{text}%"
                    params.extend([pattern, pattern])

                if since_minutes:
                    cutoff = (
                        datetime.utcnow() - timedelta(minutes=since_minutes)
                    ).isoformat() + "Z"
                    sql += " AND ts >= ?"
                    params.append(cutoff)

                sql += " ORDER BY ts DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(sql, params)
                return [self._row_to_record(row) for row in cursor.fetchall()]

        except Exception as e:
            import sys

            try:
                print(f"[LogStore] Failed to query logs: {e}", file=sys.__stderr__)
            except Exception:
                pass
            return []

    def count_by_level(self, since_minutes: int | None = None) -> dict[str, int]:
        """
        Count logs by level.

        Args:
            since_minutes: Filter to last N minutes

        Returns:
            dict mapping level to count
        """
        try:
            with self._get_connection() as conn:
                sql = "SELECT level, COUNT(*) as count FROM logs"
                params = []

                if since_minutes:
                    cutoff = (
                        datetime.utcnow() - timedelta(minutes=since_minutes)
                    ).isoformat() + "Z"
                    sql += " WHERE ts >= ?"
                    params.append(cutoff)

                sql += " GROUP BY level"

                cursor = conn.execute(sql, params)
                return {row["level"]: row["count"] for row in cursor.fetchall()}

        except Exception as e:
            import sys

            try:
                print(f"[LogStore] Failed to count logs: {e}", file=sys.__stderr__)
            except Exception:
                pass
            return {}

    def get_recent(self, count: int = 10) -> list[LogRecord]:
        """Get most recent log entries."""
        return self.query(limit=count)

    def clear_old(self, days: int = DEFAULT_LOG_RETENTION_DAYS) -> int:
        """
        Delete logs older than N days.

        Args:
            days: Keep logs from last N days

        Returns:
            Number of deleted records
        """
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
                deleted = cursor.rowcount
                conn.commit()
                return deleted
        except Exception as e:
            import sys

            try:
                print(f"[LogStore] Failed to clear old logs: {e}", file=sys.__stderr__)
            except Exception:
                pass
            return 0

    def get_db_size_bytes(self) -> int:
        """Get database file size in bytes for monitoring."""
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_log_store_instance: LogStore | None = None
_log_store_lock = threading.Lock()


def get_log_store() -> LogStore:
    """
    Get global log store instance (thread-safe singleton).

    Returns:
        Global LogStore instance
    """
    global _log_store_instance

    if _log_store_instance is not None:
        return _log_store_instance

    with _log_store_lock:
        if _log_store_instance is None:
            instance = LogStore()
            _log_store_instance = instance
        return _log_store_instance


# Convenience alias
log_store = get_log_store
