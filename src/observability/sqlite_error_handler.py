"""
Custom logging.Handler for SQLite error persistence.

Features:
- Only handles ERROR+ or records with exc_info
- Extracts structured fields from record.msg dict (set by wrap_for_formatter)
- Internal queue to prevent blocking QueueListener thread
- Non-recursive: failures go to sys.__stderr__, never back through logging

Integration with structlog:
- structlog.configure() uses ProcessorFormatter.wrap_for_formatter as final processor
- This sets record.msg to the event_dict (as a dict, not JSON string)
- SQLiteErrorHandler extracts structured fields directly from record.msg

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Non-blocking with internal queue
- Bounded queue to prevent memory exhaustion
- No recursion: insert failures write to sys.__stderr__ only

Thread Safety:
- emit() uses contextvars for re-entry guard (works with async coroutines)
- Writer thread has exclusive access to ErrorStore
- Module-level atexit registration prevents duplicate handlers
"""

import atexit
import logging
import queue
import sys
import threading
import traceback
from contextvars import ContextVar
from typing import Any, Optional

from .error_store import MAX_TRACEBACK_LENGTH, ErrorCategory, ErrorStore, get_error_store

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum queue size for pending error records
ERROR_QUEUE_SIZE = 1000

# Timeout for writer thread to wait for queue items (seconds)
WRITER_QUEUE_TIMEOUT = 1.0

# Timeout for writer thread to join on shutdown (seconds)
WRITER_SHUTDOWN_TIMEOUT = 5.0

# =============================================================================
# MODULE-LEVEL STATE (for atexit deduplication)
# =============================================================================

# Track registered handler instances for atexit cleanup
_registered_handlers: set["SQLiteErrorHandler"] = set()
_atexit_registered: bool = False
_atexit_lock = threading.Lock()

# Re-entry guard using contextvars (works with async coroutines)
_in_emit: ContextVar[bool] = ContextVar("sqlite_handler_in_emit", default=False)


class SQLiteErrorHandler(logging.Handler):
    """
    Custom logging handler that writes errors to SQLite.

    Only processes:
    - Records with level >= ERROR
    - Records with exc_info (exceptions)

    Uses an internal queue to prevent blocking the QueueListener thread.
    All failures write to sys.__stderr__ to prevent recursion.

    Thread Safety:
    - emit() is safe to call from multiple threads/coroutines
    - Re-entry guard uses contextvars (works with async)
    - Writer thread has exclusive access to ErrorStore
    - Module-level atexit handler prevents duplicate registration
    """

    def __init__(
        self,
        db_path: str = ".clarity/metrics.db",
        queue_size: int = ERROR_QUEUE_SIZE,
    ):
        """
        Initialize SQLite error handler.

        Args:
            db_path: Path to SQLite database
            queue_size: Max queue size (bounded to prevent memory exhaustion)

        Thread Safety:
            Safe to create multiple instances, but atexit cleanup is shared.
        """
        super().__init__()

        self.db_path = db_path
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._shutdown = threading.Event()
        self._closed = False

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="SQLiteErrorWriter",
            daemon=True,
        )
        self._writer_thread.start()

        # Register for module-level atexit cleanup (prevents duplicate registration)
        self._register_for_atexit()

    def _register_for_atexit(self) -> None:
        """
        Register this handler for atexit cleanup.

        Uses module-level registration to prevent duplicate atexit handlers
        when multiple SQLiteErrorHandler instances are created.
        """
        global _atexit_registered, _registered_handlers

        with _atexit_lock:
            _registered_handlers.add(self)

            if not _atexit_registered:
                atexit.register(_module_shutdown_handler)
                _atexit_registered = True

    def _get_error_store(self) -> ErrorStore:
        """
        Get error store instance.

        Uses the global singleton from get_error_store() which is thread-safe.
        This ensures all handlers share the same ErrorStore instance.

        Returns:
            Thread-safe ErrorStore singleton
        """
        return get_error_store()

    def _safe_stderr(self, message: str) -> None:
        """
        Write to sys.__stderr__ safely (non-recursive, never goes through logging).

        This is the ONLY output path for handler failures.
        """
        try:
            print(f"[SQLiteErrorHandler] {message}", file=sys.__stderr__)
        except Exception:
            pass  # Absolutely no recursion

    def _writer_loop(self):
        """Background thread that writes errors to SQLite."""
        while not self._shutdown.is_set():
            try:
                # Block for up to WRITER_QUEUE_TIMEOUT waiting for items
                record_data = self._queue.get(timeout=WRITER_QUEUE_TIMEOUT)

                if record_data is None:
                    # Shutdown signal
                    break

                # Write to SQLite
                try:
                    store = self._get_error_store()
                    store.record_from_dict(**record_data)
                except Exception as e:
                    # Non-recursive: write to stderr only
                    self._safe_stderr(f"Failed to write error: {e}")

                self._queue.task_done()

            except queue.Empty:
                # Timeout, check shutdown flag and continue
                continue
            except Exception as e:
                # Unexpected error in writer loop - non-recursive
                self._safe_stderr(f"Writer loop error: {e}")

    def _shutdown_handler(self):
        """Graceful shutdown - flush remaining items."""
        if self._closed:
            return  # Already shut down
        self._closed = True

        self._shutdown.set()

        # Signal writer thread to stop
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        # Wait for writer thread to finish (with timeout)
        self._writer_thread.join(timeout=WRITER_SHUTDOWN_TIMEOUT)

        # Unregister from module-level tracking
        with _atexit_lock:
            _registered_handlers.discard(self)

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to SQLite.

        Only processes ERROR+ or records with exc_info.
        Non-recursive: all failures go to sys.__stderr__.

        Thread Safety:
            Uses contextvars for re-entry guard, safe for both threads and
            async coroutines. Multiple coroutines on the same thread each
            have their own guard state.

        Args:
            record: Log record to process
        """
        # Re-entry guard using contextvars (works with async coroutines)
        if _in_emit.get():
            return

        # Filter: only errors or records with exceptions
        if record.levelno < logging.ERROR and not record.exc_info:
            return

        # Set re-entry guard and save token for reset
        token = _in_emit.set(True)
        try:
            # Extract data from record
            record_data = self._extract_record_data(record)

            # Queue for async write (non-blocking)
            try:
                self._queue.put_nowait(record_data)
            except queue.Full:
                # Queue full, drop record - non-recursive
                self._safe_stderr(f"Queue full, dropping error: {record.getMessage()[:100]}")

        except Exception as e:
            # Non-recursive: don't call handleError which could log
            self._safe_stderr(f"Error in emit: {e}")
        finally:
            # Reset re-entry guard to previous state
            _in_emit.reset(token)

    def _extract_record_data(self, record: logging.LogRecord) -> dict[str, Any]:
        """
        Extract structured data from log record.

        With structlog's ProcessorFormatter.wrap_for_formatter(), record.msg
        is a dict containing the event_dict. For non-structlog stdlib logs,
        record.msg is a plain string.

        Args:
            record: Log record

        Returns:
            dict of fields for ErrorStore.record_from_dict()
        """
        # Base fields
        data = {
            "level": record.levelname,
            "error_type": "LogRecord",
            "message": "",
            "component": record.name,
            "category": ErrorCategory.UNEXPECTED,
        }

        # =====================================================================
        # Extract from record.msg (structlog wrap_for_formatter sets this as dict)
        # =====================================================================
        if isinstance(record.msg, dict):
            event_dict = record.msg.copy()
            # Remove internal structlog metadata
            event_dict.pop("_record", None)
            event_dict.pop("_from_structlog", None)

            # Event name -> message
            if "event" in event_dict:
                data["message"] = event_dict["event"]

            # Error category (taxonomy)
            if "category" in event_dict:
                data["category"] = event_dict["category"]

            # Error type
            if "error_type" in event_dict:
                data["error_type"] = event_dict["error_type"]

            # Context fields
            for field in (
                "run_id",
                "session_id",
                "stream_id",
                "request_id",
                "operation",
                "component",
            ):
                if field in event_dict:
                    data[field] = event_dict[field]

            # LLM/Provider fields
            for field in (
                "model",
                "backend",
                "payload_bytes",
                "prompt_tokens",
                "completion_tokens",
            ):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Timeout debugging fields
            for field in (
                "elapsed_ms",
                "timeout_read_s",
                "timeout_write_s",
                "timeout_connect_s",
                "timeout_pool_s",
                "retry_attempt",
                "retry_max",
                "root_cause_type",
                "root_cause_message",
            ):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Tool fields
            for field in ("tool_name", "tool_timeout_s", "tool_args_keys"):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Traceback from event_dict
            if "traceback" in event_dict:
                data["traceback"] = event_dict["traceback"]

            # Formatted exception from structlog
            if "exception" in event_dict:
                data["traceback"] = event_dict["exception"]

        else:
            # Plain string message (non-structlog stdlib logs)
            data["message"] = record.getMessage()

        # =====================================================================
        # Add exception info if present (from exc_info)
        # =====================================================================
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            if exc_type:
                data["error_type"] = exc_type.__name__
            if exc_value and not data["message"]:
                data["message"] = str(exc_value)
            if exc_tb:
                data["traceback"] = "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                )[:MAX_TRACEBACK_LENGTH]

            # Classify exception type
            data["category"] = self._classify_exception(exc_type, exc_value, data.get("category"))

        # Ensure message is not empty
        if not data["message"]:
            data["message"] = f"Error from {record.name}"

        return data

    def _classify_exception(self, exc_type, exc_value, default_category: str) -> str:
        """
        Classify exception type into error category.

        Also walks the exception chain to find root cause for chained exceptions.

        Args:
            exc_type: Exception type
            exc_value: Exception value
            default_category: Fallback category

        Returns:
            Error category string
        """
        if exc_type is None:
            return default_category

        # Check the exception and its chain
        current_exc = exc_value
        while current_exc is not None:
            exc_name = type(current_exc).__name__.lower()

            # Timeout detection
            timeout_keywords = [
                "timeout",
                "timedout",
                "readtimeout",
                "writetimeout",
                "connecttimeout",
                "pooltimeout",
            ]
            if any(kw in exc_name for kw in timeout_keywords):
                return ErrorCategory.PROVIDER_TIMEOUT

            # HTTP/API errors
            api_keywords = ["httperror", "apierror", "requestexception", "connectionerror"]
            if any(kw in exc_name for kw in api_keywords):
                return ErrorCategory.PROVIDER_ERROR

            # Rate limiting
            if "ratelimit" in exc_name:
                return ErrorCategory.PROVIDER_ERROR

            # Walk the chain
            current_exc = getattr(current_exc, "__cause__", None) or getattr(
                current_exc, "__context__", None
            )

        return default_category

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

    This ensures proper cleanup even if multiple SQLiteErrorHandler instances
    were created. Only registered once via atexit, regardless of instance count.
    """
    # Take a copy to avoid modification during iteration
    with _atexit_lock:
        handlers = list(_registered_handlers)

    for handler in handlers:
        try:
            handler._shutdown_handler()
        except Exception:
            # Ignore errors during shutdown - we're exiting anyway
            pass
