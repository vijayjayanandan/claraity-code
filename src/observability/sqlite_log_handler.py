"""
Custom logging.Handler for SQLite log persistence (ALL log levels).

Writes every log record to logs.db for SQL-queryable access. Complements
the JSONL file (ground truth) with indexed, queryable storage.

Features:
- Handles ALL log levels (not just errors)
- Batch writes for high-throughput performance
- Internal queue to prevent blocking QueueListener thread
- Non-recursive: failures go to sys.__stderr__, never back through logging

Integration with structlog:
- structlog.configure() uses ProcessorFormatter.wrap_for_formatter
- This sets record.msg to the event_dict (as a dict, not JSON string)
- SQLiteLogHandler extracts structured fields directly from record.msg

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Non-blocking with internal queue
- Bounded queue to prevent memory exhaustion
- No recursion: insert failures write to sys.__stderr__ only
- Batch inserts (up to 50 records per transaction)

Thread Safety:
- emit() uses contextvars for re-entry guard (works with async coroutines)
- Writer thread has exclusive access to LogStore
- Module-level atexit registration prevents duplicate handlers
"""

import atexit
import logging
import queue
import sys
import threading
from contextvars import ContextVar
from typing import Any, Optional

from .log_store import LogStore, get_log_store

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum queue size for pending log records (larger than error handler
# because ALL logs go through this handler)
LOG_QUEUE_SIZE = 5000

# Batch size for SQLite inserts (flush this many records in one transaction)
BATCH_SIZE = 50

# Timeout for writer thread to wait for queue items (seconds)
WRITER_QUEUE_TIMEOUT = 0.5

# Timeout for writer thread to join on shutdown (seconds)
WRITER_SHUTDOWN_TIMEOUT = 5.0

# =============================================================================
# MODULE-LEVEL STATE
# =============================================================================

_registered_handlers: set["SQLiteLogHandler"] = set()
_atexit_registered: bool = False
_atexit_lock = threading.Lock()

# Separate re-entry guard from SQLiteErrorHandler to avoid interference
_in_log_emit: ContextVar[bool] = ContextVar("sqlite_log_handler_in_emit", default=False)


class SQLiteLogHandler(logging.Handler):
    """
    Custom logging handler that writes ALL log records to SQLite logs.db.

    Uses an internal queue with a background writer thread that batches
    inserts for performance. Non-blocking -- never stalls the caller.

    Thread Safety:
    - emit() is safe to call from multiple threads/coroutines
    - Re-entry guard uses contextvars (works with async)
    - Writer thread has exclusive access to LogStore
    """

    def __init__(
        self,
        db_path: str = ".claraity/logs/logs.db",
        queue_size: int = LOG_QUEUE_SIZE,
        batch_size: int = BATCH_SIZE,
    ):
        """
        Initialize SQLite log handler.

        Args:
            db_path: Path to SQLite database
            queue_size: Max queue size (bounded to prevent memory exhaustion)
            batch_size: Number of records to batch per transaction
        """
        super().__init__()

        self.db_path = db_path
        self.batch_size = batch_size
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._shutdown = threading.Event()
        self._closed = False

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="SQLiteLogWriter",
            daemon=True,
        )
        self._writer_thread.start()

        # Register for module-level atexit cleanup
        self._register_for_atexit()

    def _register_for_atexit(self) -> None:
        """Register this handler for atexit cleanup."""
        global _atexit_registered, _registered_handlers

        with _atexit_lock:
            _registered_handlers.add(self)

            if not _atexit_registered:
                atexit.register(_module_shutdown_handler)
                _atexit_registered = True

    def _get_log_store(self) -> LogStore:
        """Get log store instance (thread-safe singleton)."""
        return get_log_store()

    def _safe_stderr(self, message: str) -> None:
        """Write to sys.__stderr__ safely (non-recursive)."""
        try:
            print(f"[SQLiteLogHandler] {message}", file=sys.__stderr__)
        except Exception:
            pass

    def _writer_loop(self):
        """Background thread that batches and writes logs to SQLite."""
        batch = []

        while not self._shutdown.is_set():
            try:
                # Block for up to WRITER_QUEUE_TIMEOUT
                record_data = self._queue.get(timeout=WRITER_QUEUE_TIMEOUT)

                if record_data is None:
                    # Shutdown signal -- flush remaining batch
                    if batch:
                        self._flush_batch(batch)
                    self._queue.task_done()
                    break

                batch.append(record_data)
                self._queue.task_done()

                # Drain up to batch_size from queue (non-blocking)
                while len(batch) < self.batch_size:
                    try:
                        item = self._queue.get_nowait()
                        if item is None:
                            # Shutdown signal mid-drain
                            self._flush_batch(batch)
                            self._queue.task_done()
                            return
                        batch.append(item)
                        self._queue.task_done()
                    except queue.Empty:
                        break

                # Flush the batch
                self._flush_batch(batch)
                batch = []

            except queue.Empty:
                # Timeout -- flush any partial batch
                if batch:
                    self._flush_batch(batch)
                    batch = []
                continue
            except Exception as e:
                self._safe_stderr(f"Writer loop error: {e}")

    def _flush_batch(self, batch):
        """Write batch of records to SQLite in single transaction."""
        if not batch:
            return
        try:
            store = self._get_log_store()
            store.record_batch(batch)
        except Exception as e:
            self._safe_stderr(f"Failed to write log batch ({len(batch)} records): {e}")

    def _shutdown_handler(self):
        """Graceful shutdown -- flush remaining items."""
        if self._closed:
            return
        self._closed = True

        self._shutdown.set()

        # Signal writer thread to stop
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        # Wait for writer thread to finish
        self._writer_thread.join(timeout=WRITER_SHUTDOWN_TIMEOUT)

        # Unregister from module-level tracking
        with _atexit_lock:
            _registered_handlers.discard(self)

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to the SQLite queue (non-blocking).

        Thread Safety:
            Uses contextvars for re-entry guard, safe for both threads
            and async coroutines.

        Args:
            record: Log record to process
        """
        # Re-entry guard
        if _in_log_emit.get():
            return

        token = _in_log_emit.set(True)
        try:
            record_data = self._extract_record_data(record)

            try:
                self._queue.put_nowait(record_data)
            except queue.Full:
                self._safe_stderr(f"Queue full, dropping log: {record.getMessage()[:80]}")

        except Exception as e:
            self._safe_stderr(f"Error in emit: {e}")
        finally:
            _in_log_emit.reset(token)

    def _extract_record_data(self, record: logging.LogRecord) -> dict[str, Any]:
        """
        Extract structured data from log record for LogStore.record_batch().

        Handles both structlog dict records (record.msg is dict) and
        plain stdlib string records.

        Args:
            record: Log record

        Returns:
            dict of fields for LogStore.record_from_dict() / record_batch()
        """
        data: dict[str, Any] = {
            "level": record.levelname,
            "event": "",
        }

        if isinstance(record.msg, dict):
            event_dict = record.msg.copy()
            # Remove internal structlog metadata
            event_dict.pop("_record", None)
            event_dict.pop("_from_structlog", None)

            # Event name
            data["event"] = event_dict.pop("event", "")

            # Logger name
            if "logger" in event_dict:
                data["logger"] = event_dict.pop("logger")
            else:
                data["logger"] = record.name

            # Timestamp (use structlog's if available)
            if "timestamp" in event_dict:
                data["ts"] = event_dict.pop("timestamp")

            # Pop 'level' to avoid passing it as extra
            event_dict.pop("level", None)

            # Context fields (named columns)
            for field in (
                "run_id",
                "session_id",
                "stream_id",
                "request_id",
                "component",
                "operation",
            ):
                if field in event_dict:
                    data[field] = event_dict.pop(field)

            # Source location from structlog
            if "filename" in event_dict:
                data["source_file"] = event_dict.pop("filename")
            if "lineno" in event_dict:
                data["source_line"] = event_dict.pop("lineno")
            if "func_name" in event_dict:
                data["source_function"] = event_dict.pop("func_name")

            # Everything else becomes extra_json (handled by record_batch)
            data.update(event_dict)

        else:
            # Plain string message
            data["event"] = record.getMessage()
            data["logger"] = record.name

        # Source from LogRecord as fallback
        if "source_file" not in data:
            data["source_file"] = record.filename
            data["source_line"] = record.lineno
            data["source_function"] = record.funcName

        return data

    def close(self):
        """Close the handler and flush remaining items."""
        self._shutdown_handler()
        super().close()


# =============================================================================
# MODULE-LEVEL SHUTDOWN HANDLER
# =============================================================================


def _module_shutdown_handler() -> None:
    """
    Module-level atexit handler that shuts down all registered handlers.

    Only registered once via atexit, regardless of instance count.
    """
    with _atexit_lock:
        handlers = list(_registered_handlers)

    for handler in handlers:
        try:
            handler._shutdown_handler()
        except Exception:
            pass
