"""
SQLite error store for queryable error persistence.

Schema designed for fast queries on:
- session_id (correlation)
- category (error taxonomy)
- ts (time-based queries)
- component (source filtering)

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Thread-safe with RLock
- Truncate traceback to 32KB
- Auto-cleanup of old errors

Thread Safety:
- All public methods are thread-safe via RLock
- Global singleton uses proper locking pattern (lock always held for init)
- Connection per operation ensures SQLite thread safety
"""

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict, fields as dataclass_fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum traceback length to store (prevents DB bloat from huge stack traces)
MAX_TRACEBACK_LENGTH = 32768

# Default database path
DEFAULT_DB_PATH = ".clarity/metrics.db"

# Default retention period for old error cleanup
DEFAULT_RETENTION_DAYS = 30

# Default query limit
DEFAULT_QUERY_LIMIT = 100


# =============================================================================
# ERROR TAXONOMY
# =============================================================================

class ErrorCategory:
    """Controlled error taxonomy for meaningful queries."""
    PROVIDER_TIMEOUT = 'provider_timeout'  # WriteTimeout, ReadTimeout from httpx
    PROVIDER_ERROR = 'provider_error'      # HTTP 5xx, invalid response
    TOOL_TIMEOUT = 'tool_timeout'          # Tool exceeded timeout_s
    TOOL_ERROR = 'tool_error'              # Tool execution failed
    UI_GUARD_SKIPPED = 'ui_guard_skipped'  # Pause widget not mounted
    BUDGET_PAUSE = 'budget_pause'          # Max wall time / max tool calls
    UNEXPECTED = 'unexpected'              # Uncategorized


@dataclass
class ErrorRecord:
    """Structured error record for storage and queries."""
    id: str
    ts: str
    level: str
    category: str
    error_type: str
    message: str
    traceback: Optional[str] = None
    component: Optional[str] = None
    operation: Optional[str] = None
    run_id: Optional[str] = None  # Process-level identifier
    session_id: Optional[str] = None
    stream_id: Optional[str] = None
    request_id: Optional[str] = None
    model: Optional[str] = None
    backend: Optional[str] = None
    tool_name: Optional[str] = None
    tool_timeout_s: Optional[float] = None
    elapsed_ms: Optional[float] = None  # Standardized to milliseconds
    payload_bytes: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    # Timeout debugging fields
    timeout_read_s: Optional[float] = None
    timeout_write_s: Optional[float] = None
    timeout_connect_s: Optional[float] = None
    timeout_pool_s: Optional[float] = None
    retry_attempt: Optional[int] = None
    retry_max: Optional[int] = None
    root_cause_type: Optional[str] = None
    root_cause_message: Optional[str] = None
    tool_args_keys: Optional[str] = None  # JSON list of arg keys
    extra_json: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# =============================================================================
# ERROR STORE
# =============================================================================

class ErrorStore:
    """
    SQLite-based error storage for queryable error persistence.

    Features:
    - Thread-safe operations
    - Automatic schema migration
    - Time-based cleanup
    - Category-based queries
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initialize error store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"[OK] ErrorStore initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Thread-safe context manager for database connections."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS errors (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    traceback TEXT,
                    component TEXT,
                    operation TEXT,
                    run_id TEXT,
                    session_id TEXT,
                    stream_id TEXT,
                    request_id TEXT,
                    model TEXT,
                    backend TEXT,
                    tool_name TEXT,
                    tool_timeout_s REAL,
                    elapsed_ms REAL,
                    payload_bytes INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    timeout_read_s REAL,
                    timeout_write_s REAL,
                    timeout_connect_s REAL,
                    timeout_pool_s REAL,
                    retry_attempt INTEGER,
                    retry_max INTEGER,
                    root_cause_type TEXT,
                    root_cause_message TEXT,
                    tool_args_keys TEXT,
                    extra_json TEXT
                )
            """)

            # Add new columns to existing table (migration)
            new_columns = [
                ("run_id", "TEXT"),
                ("elapsed_ms", "REAL"),  # New standardized column
                ("timeout_read_s", "REAL"),
                ("timeout_write_s", "REAL"),
                ("timeout_connect_s", "REAL"),
                ("timeout_pool_s", "REAL"),
                ("retry_attempt", "INTEGER"),
                ("retry_max", "INTEGER"),
                ("root_cause_type", "TEXT"),
                ("root_cause_message", "TEXT"),
                ("tool_args_keys", "TEXT"),
            ]
            for col_name, col_type in new_columns:
                try:
                    conn.execute(f"ALTER TABLE errors ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Create indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_ts ON errors(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_session ON errors(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_category ON errors(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_component ON errors(component)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_run ON errors(run_id)")

            conn.commit()

    def record(self, error: ErrorRecord) -> str:
        """
        Record an error.

        Args:
            error: ErrorRecord to store

        Returns:
            Error ID
        """
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO errors (
                        id, ts, level, category, error_type, message, traceback,
                        component, operation, run_id, session_id, stream_id, request_id,
                        model, backend, tool_name, tool_timeout_s, elapsed_ms,
                        payload_bytes, prompt_tokens, completion_tokens,
                        timeout_read_s, timeout_write_s, timeout_connect_s, timeout_pool_s,
                        retry_attempt, retry_max, root_cause_type, root_cause_message,
                        tool_args_keys, extra_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    error.id, error.ts, error.level, error.category, error.error_type,
                    error.message, error.traceback, error.component, error.operation,
                    error.run_id, error.session_id, error.stream_id, error.request_id,
                    error.model, error.backend, error.tool_name, error.tool_timeout_s,
                    error.elapsed_ms, error.payload_bytes, error.prompt_tokens,
                    error.completion_tokens, error.timeout_read_s, error.timeout_write_s,
                    error.timeout_connect_s, error.timeout_pool_s, error.retry_attempt,
                    error.retry_max, error.root_cause_type, error.root_cause_message,
                    error.tool_args_keys, error.extra_json
                ))
                conn.commit()
            return error.id
        except Exception as e:
            logger.error(f"[FAIL] Failed to record error: {e}")
            return error.id

    def record_from_dict(
        self,
        level: str,
        category: str,
        error_type: str,
        message: str,
        **kwargs
    ) -> str:
        """
        Record an error from individual fields.

        Args:
            level: Log level (ERROR, CRITICAL)
            category: Error category from ErrorCategory
            error_type: Exception class name
            message: Error message
            **kwargs: Additional fields (traceback, component, etc.)

        Returns:
            Error ID
        """
        error_id = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat() + 'Z'

        # Truncate traceback to prevent DB bloat
        traceback_str = kwargs.get('traceback')
        if traceback_str and len(traceback_str) > MAX_TRACEBACK_LENGTH:
            traceback_str = traceback_str[:MAX_TRACEBACK_LENGTH] + '\n...[truncated]'
            kwargs['traceback'] = traceback_str

        # Handle extra fields as JSON (avoid duplicating traceback/exception)
        extra_fields = {}
        known_fields = {
            # Core fields
            'traceback', 'exception',  # Exception blobs - never duplicate
            'component', 'operation', 'run_id', 'session_id', 'stream_id',
            'request_id', 'model', 'backend', 'tool_name', 'tool_timeout_s',
            'elapsed_ms', 'payload_bytes', 'prompt_tokens', 'completion_tokens',
            # Timeout debugging fields
            'timeout_read_s', 'timeout_write_s', 'timeout_connect_s', 'timeout_pool_s',
            'retry_attempt', 'retry_max', 'root_cause_type', 'root_cause_message',
            'tool_args_keys',
        }
        for key, value in list(kwargs.items()):
            if key not in known_fields:
                extra_fields[key] = value
                del kwargs[key]
            elif key == 'exception':
                # 'exception' is an alias for 'traceback', extract if needed
                if 'traceback' not in kwargs and value:
                    kwargs['traceback'] = value
                del kwargs[key]

        if extra_fields:
            kwargs['extra_json'] = json.dumps(extra_fields, default=str)

        error = ErrorRecord(
            id=error_id,
            ts=ts,
            level=level,
            category=category,
            error_type=error_type,
            message=message,
            **kwargs
        )

        return self.record(error)

    def _row_to_record(self, row: sqlite3.Row) -> ErrorRecord:
        """
        Convert a database row to an ErrorRecord.

        Handles backward compatibility with old column names (elapsed_s -> elapsed_ms).
        """
        data = dict(row)

        # Handle backward compatibility: elapsed_s -> elapsed_ms
        if 'elapsed_s' in data and 'elapsed_ms' not in data:
            elapsed_s = data.pop('elapsed_s')
            if elapsed_s is not None:
                data['elapsed_ms'] = elapsed_s * 1000.0  # Convert seconds to milliseconds

        # Remove any columns that don't exist in ErrorRecord
        valid_fields = {f.name for f in dataclass_fields(ErrorRecord)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return ErrorRecord(**filtered_data)

    def query(
        self,
        session_id: Optional[str] = None,
        category: Optional[str] = None,
        component: Optional[str] = None,
        since_minutes: Optional[int] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> List[ErrorRecord]:
        """
        Query errors with filters.

        Args:
            session_id: Filter by session
            category: Filter by error category
            component: Filter by component
            since_minutes: Filter to last N minutes
            limit: Maximum results

        Returns:
            List of ErrorRecord
        """
        try:
            with self._get_connection() as conn:
                query = "SELECT * FROM errors WHERE 1=1"
                params = []

                if session_id:
                    query += " AND session_id = ?"
                    params.append(session_id)

                if category:
                    query += " AND category = ?"
                    params.append(category)

                if component:
                    query += " AND component = ?"
                    params.append(component)

                if since_minutes:
                    cutoff = (datetime.utcnow() - timedelta(minutes=since_minutes)).isoformat() + 'Z'
                    query += " AND ts >= ?"
                    params.append(cutoff)

                query += " ORDER BY ts DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                return [self._row_to_record(row) for row in rows]

        except Exception as e:
            logger.error(f"[FAIL] Failed to query errors: {e}")
            return []

    def count_by_category(self, since_minutes: Optional[int] = None) -> Dict[str, int]:
        """
        Count errors by category.

        Args:
            since_minutes: Filter to last N minutes

        Returns:
            Dict mapping category to count
        """
        try:
            with self._get_connection() as conn:
                query = "SELECT category, COUNT(*) as count FROM errors"
                params = []

                if since_minutes:
                    cutoff = (datetime.utcnow() - timedelta(minutes=since_minutes)).isoformat() + 'Z'
                    query += " WHERE ts >= ?"
                    params.append(cutoff)

                query += " GROUP BY category"

                cursor = conn.execute(query, params)
                return {row['category']: row['count'] for row in cursor.fetchall()}

        except Exception as e:
            logger.error(f"[FAIL] Failed to count errors: {e}")
            return {}

    def get_recent(self, count: int = 10) -> List[ErrorRecord]:
        """
        Get most recent errors.

        Args:
            count: Number of errors to return

        Returns:
            List of ErrorRecord
        """
        return self.query(limit=count)

    def clear_old(self, days: int = DEFAULT_RETENTION_DAYS) -> int:
        """
        Delete errors older than N days.

        Args:
            days: Keep errors from last N days

        Returns:
            Number of deleted records
        """
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + 'Z'
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM errors WHERE ts < ?",
                    (cutoff,)
                )
                deleted = cursor.rowcount
                conn.commit()
                logger.info(f"[OK] Deleted {deleted} errors older than {days} days")
                return deleted
        except Exception as e:
            logger.error(f"[FAIL] Failed to clear old errors: {e}")
            return 0


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_error_store_instance: Optional[ErrorStore] = None
_error_store_lock = threading.Lock()


def get_error_store() -> ErrorStore:
    """
    Get global error store instance (thread-safe singleton).

    Thread Safety:
    - Uses lock-based singleton pattern (not double-checked locking)
    - Instance is fully constructed before assignment to global
    - Safe for concurrent access from multiple threads

    Returns:
        Global ErrorStore instance
    """
    global _error_store_instance

    # Fast path: instance already exists
    if _error_store_instance is not None:
        return _error_store_instance

    # Slow path: acquire lock and create instance
    with _error_store_lock:
        # Check again under lock (another thread may have created it)
        if _error_store_instance is None:
            # Create instance in local variable first (ensures full construction)
            instance = ErrorStore()
            # Only assign to global after full construction
            _error_store_instance = instance
        return _error_store_instance


# Convenience alias
error_store = get_error_store
