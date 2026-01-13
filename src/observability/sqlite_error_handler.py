"""
Custom logging.Handler for SQLite error persistence.

Features:
- Only handles ERROR+ or records with exc_info
- Extracts structured fields from structlog _structlog_event_dict
- Internal queue to prevent blocking QueueListener thread
- Non-recursive: failures go to sys.__stderr__, never back through logging

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Non-blocking with internal queue
- Bounded queue to prevent memory exhaustion
- No recursion: insert failures write to sys.__stderr__ only
"""

import atexit
import logging
import queue
import sys
import threading
import traceback
from typing import Any, Dict, Optional

from .error_store import ErrorStore, ErrorCategory, get_error_store


class SQLiteErrorHandler(logging.Handler):
    """
    Custom logging handler that writes errors to SQLite.

    Only processes:
    - Records with level >= ERROR
    - Records with exc_info (exceptions)

    Uses an internal queue to prevent blocking the QueueListener thread.
    All failures write to sys.__stderr__ to prevent recursion.
    """

    def __init__(
        self,
        db_path: str = ".clarity/metrics.db",
        queue_size: int = 1000,
    ):
        """
        Initialize SQLite error handler.

        Args:
            db_path: Path to SQLite database
            queue_size: Max queue size (bounded to prevent memory exhaustion)
        """
        super().__init__()

        self.db_path = db_path
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._shutdown = threading.Event()
        self._error_store: Optional[ErrorStore] = None
        self._in_emit = threading.local()  # Re-entry guard

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="SQLiteErrorWriter",
            daemon=True,
        )
        self._writer_thread.start()

        # Register shutdown handler
        atexit.register(self._shutdown_handler)

    def _get_error_store(self) -> ErrorStore:
        """Lazy initialization of error store."""
        if self._error_store is None:
            self._error_store = ErrorStore(self.db_path)
        return self._error_store

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
                # Block for up to 1 second waiting for items
                record_data = self._queue.get(timeout=1.0)

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
        self._shutdown.set()

        # Signal writer thread to stop
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        # Wait for writer thread to finish (with timeout)
        self._writer_thread.join(timeout=5.0)

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to SQLite.

        Only processes ERROR+ or records with exc_info.
        Non-recursive: all failures go to sys.__stderr__.

        Args:
            record: Log record to process
        """
        # Re-entry guard (per-thread)
        if getattr(self._in_emit, 'active', False):
            return

        # Filter: only errors or records with exceptions
        if record.levelno < logging.ERROR and not record.exc_info:
            return

        try:
            self._in_emit.active = True

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
            self._in_emit.active = False

    def _extract_record_data(self, record: logging.LogRecord) -> Dict[str, Any]:
        """
        Extract structured data from log record.

        Prioritizes structlog _structlog_event_dict for consistent field extraction.

        Args:
            record: Log record

        Returns:
            Dict of fields for ErrorStore.record_from_dict()
        """
        # Base fields
        data = {
            'level': record.levelname,
            'error_type': 'LogRecord',
            'message': record.getMessage(),
            'component': record.name,
            'category': ErrorCategory.UNEXPECTED,
        }

        # =====================================================================
        # Extract from structlog _structlog_event_dict (primary source)
        # This is set by our add_structlog_context processor
        # =====================================================================
        if hasattr(record, '_structlog_event_dict') and isinstance(record._structlog_event_dict, dict):
            event_dict = record._structlog_event_dict

            # Event name
            if 'event' in event_dict:
                data['message'] = event_dict['event']

            # Error category (taxonomy)
            if 'category' in event_dict:
                data['category'] = event_dict['category']

            # Error type
            if 'error_type' in event_dict:
                data['error_type'] = event_dict['error_type']

            # Context fields
            for field in ('run_id', 'session_id', 'stream_id', 'request_id', 'operation', 'component'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # LLM/Provider fields
            for field in ('model', 'backend', 'payload_bytes', 'prompt_tokens', 'completion_tokens'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Timeout debugging fields (standardized to elapsed_ms)
            for field in ('elapsed_ms', 'timeout_read_s', 'timeout_write_s',
                          'timeout_connect_s', 'timeout_pool_s', 'retry_attempt', 'retry_max',
                          'root_cause_type', 'root_cause_message'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Tool fields
            for field in ('tool_name', 'tool_timeout_s', 'tool_args_keys'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Traceback from event_dict
            if 'traceback' in event_dict:
                data['traceback'] = event_dict['traceback']

            # Formatted exception from structlog
            if 'exception' in event_dict:
                data['traceback'] = event_dict['exception']

        # =====================================================================
        # Fallback: legacy extra.event_dict pattern (for backwards compat)
        # =====================================================================
        elif hasattr(record, 'event_dict') and isinstance(record.event_dict, dict):
            event_dict = record.event_dict

            data['category'] = event_dict.get('category', ErrorCategory.UNEXPECTED)
            data['error_type'] = event_dict.get('error_type', data['error_type'])
            data['message'] = event_dict.get('event', data['message'])

            # Context fields
            for field in ('run_id', 'session_id', 'stream_id', 'request_id', 'operation'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # LLM fields
            for field in ('model', 'backend', 'payload_bytes', 'prompt_tokens', 'completion_tokens'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Tool fields
            for field in ('tool_name', 'tool_timeout_s'):
                if field in event_dict:
                    data[field] = event_dict[field]

            # Timing (standardized to elapsed_ms)
            if 'elapsed_ms' in event_dict:
                data['elapsed_ms'] = event_dict['elapsed_ms']

            if 'traceback' in event_dict:
                data['traceback'] = event_dict['traceback']

        # =====================================================================
        # Add exception info if present (from exc_info)
        # =====================================================================
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            if exc_type:
                data['error_type'] = exc_type.__name__
            if exc_value:
                # Only override message if we don't have a better one
                if data['message'] == record.getMessage():
                    data['message'] = str(exc_value) or data['message']
            if exc_tb:
                data['traceback'] = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))[:32768]

            # Classify exception type
            data['category'] = self._classify_exception(exc_type, exc_value, data.get('category'))

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
            timeout_keywords = ['timeout', 'timedout', 'readtimeout', 'writetimeout',
                                'connecttimeout', 'pooltimeout']
            if any(kw in exc_name for kw in timeout_keywords):
                return ErrorCategory.PROVIDER_TIMEOUT

            # HTTP/API errors
            api_keywords = ['httperror', 'apierror', 'requestexception', 'connectionerror']
            if any(kw in exc_name for kw in api_keywords):
                return ErrorCategory.PROVIDER_ERROR

            # Rate limiting
            if 'ratelimit' in exc_name:
                return ErrorCategory.PROVIDER_ERROR

            # Walk the chain
            current_exc = getattr(current_exc, '__cause__', None) or getattr(current_exc, '__context__', None)

        return default_category

    def close(self):
        """Close the handler and flush remaining items."""
        self._shutdown_handler()
        super().close()
