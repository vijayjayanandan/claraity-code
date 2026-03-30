"""
Production-grade logging configuration with structlog + stdlib.

Architecture:
- structlog: Context binding, JSON formatting, key=value logging
- stdlib: Transport layer (handlers, rotation, queueing)
- QueueHandler/QueueListener: Non-blocking I/O for async safety

Flow:
    structlog.get_logger() -> stdlib Logger -> QueueHandler -> QueueListener
                                                                    |
                                                   +----------------+----------------+
                                                   |                                 |
                                             RotatingFile                      SQLiteError
                                             (JSONL)                           Handler

NO console/stderr output - all logs go to file only.
User-facing messages should use Rich console.print() instead.

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Non-blocking writes via QueueHandler
- Crash-safe via excepthooks
- Context propagation via contextvars
"""

import atexit
import json
import logging
import logging.handlers
import os
import platform
import queue
import re
import signal
import sys
import threading
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from src.observability.sqlite_error_handler import SQLiteErrorHandler
    from src.observability.sqlite_log_handler import SQLiteLogHandler

import structlog
from structlog.stdlib import BoundLogger

# =============================================================================
# CONSTANTS
# =============================================================================

# Queue size for non-blocking logging (drops when full)
LOG_QUEUE_SIZE = 10000

# Maximum length for redacted strings (longer strings are truncated)
REDACT_MAX_LENGTH = 500

# Rate limit interval for drop warnings (seconds)
DROP_WARNING_INTERVAL_SECONDS = 10.0

# Maximum traceback length to store (prevents log/DB bloat from huge stack traces)
# Same value as error_store.MAX_TRACEBACK_LENGTH for consistency
MAX_TRACEBACK_LENGTH = 32768

# =============================================================================
# CONTEXT VARIABLES (for async propagation)
# =============================================================================

run_id: ContextVar[str] = ContextVar("run_id", default="")  # Process-level ID, set once at startup
session_id: ContextVar[str] = ContextVar("session_id", default="")
request_id: ContextVar[str] = ContextVar("request_id", default="")
turn_id: ContextVar[int] = ContextVar("turn_id", default=0)  # Incremented per user message
component: ContextVar[str] = ContextVar("component", default="")
operation: ContextVar[str] = ContextVar("operation", default="")

# =============================================================================
# GLOBALS
# =============================================================================

_queue_listener: logging.handlers.QueueListener | None = None
_log_queue: queue.Queue | None = None
_sqlite_handler: Optional["SQLiteErrorHandler"] = None  # Forward reference
_sqlite_log_handler: Optional["SQLiteLogHandler"] = None  # Forward reference
_configured: bool = False
_shutting_down: bool = False
_original_sigint_handler = None
_original_sigterm_handler = None

# =============================================================================
# REDACTION
# =============================================================================

# Patterns to redact (compiled for performance)
_REDACT_PATTERNS = [
    # Generic key=value patterns for common sensitive fields
    (
        re.compile(
            r'(api[_-]?key|apikey|authorization|auth[_-]?token|bearer|secret|password|passwd|pwd)\s*[=:]\s*["\']?[\w\-\.]+["\']?',
            re.IGNORECASE,
        ),
        r"\1=***REDACTED***",
    ),
    # OpenAI API keys (sk-...)
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE), "***OPENAI_API_KEY***"),
    # Anthropic API keys (sk-ant-...)
    (re.compile(r"(sk-ant-[a-zA-Z0-9\-_]{20,})", re.IGNORECASE), "***ANTHROPIC_API_KEY***"),
    # AWS Access Key IDs (AKIA...)
    (re.compile(r"(AKIA[0-9A-Z]{16})", re.IGNORECASE), "***AWS_ACCESS_KEY***"),
    # AWS Secret Access Keys (40 character base64-like strings after aws_secret)
    (
        re.compile(
            r'(aws_secret_access_key\s*[=:]\s*["\']?)[A-Za-z0-9/+=]{40}["\']?', re.IGNORECASE
        ),
        r"\1***AWS_SECRET_KEY***",
    ),
    # Bearer tokens
    (re.compile(r"(Bearer\s+[\w\-\.]+)", re.IGNORECASE), "Bearer ***REDACTED***"),
    # Private keys (PEM format) - match the header only to avoid huge replacements
    (
        re.compile(
            r"-----BEGIN\s+(RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----", re.IGNORECASE
        ),
        "***PRIVATE_KEY_HEADER***",
    ),
    # Database connection strings with passwords
    (
        re.compile(r"((?:postgres|mysql|mongodb|redis)://[^:]+:)[^@]+(@)", re.IGNORECASE),
        r"\1***PASSWORD***\2",
    ),
    # Generic token patterns (token=..., access_token=...)
    (
        re.compile(
            r'((?:access_|refresh_|auth_)?token\s*[=:]\s*["\']?)[a-zA-Z0-9\-_.]{20,}["\']?',
            re.IGNORECASE,
        ),
        r"\1***TOKEN***",
    ),
]

# Keys to fully redact in dicts
_REDACT_KEYS = {
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "private_key",
    "password",
    "passwd",
    "pwd",
    "bearer",
    "token",
    "aws_secret_access_key",
    "aws_access_key_id",
    "anthropic_api_key",
    "openai_api_key",
    "database_url",
    "connection_string",
}


def _redact_value(value: Any, max_length: int = REDACT_MAX_LENGTH) -> Any:
    """Redact sensitive values and truncate long strings."""
    if isinstance(value, str):
        # Truncate long strings (like prompts)
        if len(value) > max_length:
            value = value[:max_length] + f"...[truncated {len(value) - max_length} chars]"
        # Apply redaction patterns
        for pattern, replacement in _REDACT_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    elif isinstance(value, dict):
        return _redact_dict(value, max_length)
    elif isinstance(value, list | tuple):
        return [_redact_value(v, max_length) for v in value[:10]]  # Limit list length
    return value


def _redact_dict(d: dict[str, Any], max_length: int = REDACT_MAX_LENGTH) -> dict[str, Any]:
    """Recursively redact sensitive keys in dictionaries."""
    result = {}
    for key, value in d.items():
        if key.lower() in _REDACT_KEYS:
            result[key] = "***REDACTED***"
        else:
            result[key] = _redact_value(value, max_length)
    return result


def redact_sensitive(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor to redact sensitive information."""
    return _redact_dict(event_dict)


# =============================================================================
# CONTEXT INJECTION (structlog processor)
# =============================================================================


def add_context(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor to inject context variables."""
    ctx_run = run_id.get()
    ctx_session = session_id.get()
    ctx_request = request_id.get()
    ctx_turn = turn_id.get()
    ctx_component = component.get()
    ctx_operation = operation.get()

    if ctx_run:
        event_dict["run_id"] = ctx_run
    if ctx_session:
        event_dict["session_id"] = ctx_session
    if ctx_request:
        event_dict["request_id"] = ctx_request
    if ctx_turn:
        event_dict["turn_id"] = ctx_turn
    if ctx_component:
        event_dict["component"] = ctx_component
    if ctx_operation:
        event_dict["operation"] = ctx_operation

    return event_dict


# =============================================================================
# PROCESSOR FORMATTER FACTORIES
# =============================================================================
#
# These factory functions create ProcessorFormatter instances for different
# output formats. ProcessorFormatter extracts the event_dict from record.msg
# (set by wrap_for_formatter) and applies final rendering processors.
#


def create_json_formatter() -> structlog.stdlib.ProcessorFormatter:
    """
    Create a ProcessorFormatter that renders to JSON lines.

    Used for JSONL file output (.claraity/logs/app.jsonl).
    """
    return structlog.stdlib.ProcessorFormatter(
        # These processors run on the event_dict extracted from record.msg
        processors=[
            # Remove internal structlog metadata (_record, _from_structlog)
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Add source location from LogRecord
            _add_source_location,
            # Render to JSON
            structlog.processors.JSONRenderer(),
        ],
        # For non-structlog records (plain logging calls), use these processors
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            add_context,
        ],
    )


def create_console_formatter() -> structlog.stdlib.ProcessorFormatter:
    """
    Create a ProcessorFormatter that renders for console output.

    Used for CLI stdout and TUI stderr.
    """
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _console_renderer,
        ],
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            add_context,
        ],
    )


def _add_source_location(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor to add source location from LogRecord."""
    record = event_dict.get("_record")
    if record:
        event_dict["source"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }
    return event_dict


def _console_renderer(logger: Any, method_name: str, event_dict: dict[str, Any]) -> str:
    """Simple console renderer: [LEVEL] logger: event"""
    level = event_dict.get("level", "INFO").upper()
    logger_name = event_dict.get("logger", "root")
    event = event_dict.get("event", str(event_dict))
    return f"[{level}] {logger_name}: {event}"


# =============================================================================
# LEGACY FORMATTERS (for backwards compatibility with non-structlog records)
# =============================================================================


class StructlogJSONFormatter(logging.Formatter):
    """
    Fallback JSON formatter for non-structlog records.

    NOTE: With ProcessorFormatter, this is rarely needed. Kept for backwards
    compatibility with any code that might reference it directly.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON line."""
        # Base entry with timestamp
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }

        # Check if record.msg is a dict (from wrap_for_formatter)
        if isinstance(record.msg, dict):
            event_dict = record.msg.copy()
            # Remove internal keys
            event_dict.pop("_record", None)
            event_dict.pop("_from_structlog", None)
            for key, value in event_dict.items():
                if key == "event":
                    log_entry["event"] = value
                elif key not in ("level", "logger", "timestamp"):
                    log_entry[key] = value
        else:
            # Plain string message
            log_entry["event"] = record.getMessage()

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            log_entry["exception"] = self.formatException(record.exc_info)[:MAX_TRACEBACK_LENGTH]

        # Add source location
        log_entry["source"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class StructlogConsoleFormatter(logging.Formatter):
    """
    Fallback console formatter for non-structlog records.

    NOTE: With ProcessorFormatter, this is rarely needed. Kept for backwards
    compatibility with any code that might reference it directly.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format for console output."""
        # Check if record.msg is a dict (from wrap_for_formatter)
        if isinstance(record.msg, dict):
            event = record.msg.get("event", str(record.msg))
            return f"[{record.levelname}] {record.name}: {event}"

        return f"[{record.levelname}] {record.name}: {record.getMessage()}"


# =============================================================================
# BOUNDED QUEUE HANDLER (with drop policy)
# =============================================================================

# Module-level drop statistics (shared across all BoundedQueueHandler instances)
# This aggregation is intentional: we want a single drop count for all logging
_total_drop_count: int = 0
_last_drop_warning_time: float = 0.0
_drop_stats_lock = threading.Lock()


class BoundedQueueHandler(logging.handlers.QueueHandler):
    """
    QueueHandler that drops messages when queue is full instead of blocking.

    This prevents log producers from being blocked by slow consumers,
    which is critical for non-blocking async code.

    IMPORTANT: We override prepare() to NOT modify record.msg, because
    ProcessorFormatter expects record.msg to remain a dict (from wrap_for_formatter).
    The default QueueHandler.prepare() calls self.format(record) which converts
    the dict to a string, breaking ProcessorFormatter.

    Drop Statistics:
        Drop count is tracked at module level (shared across all instances).
        This is intentional: we want aggregate drop metrics regardless of
        how many handler instances exist. Access via get_drop_count().
    """

    def __init__(self, queue: queue.Queue):
        """
        Initialize bounded queue handler.

        Args:
            queue: Queue to write log records to
        """
        super().__init__(queue)
        # Instance-level drop count (for per-handler tracking if needed)
        self._instance_drop_count: int = 0

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        """
        Prepare record for queuing WITHOUT modifying record.msg.

        The default QueueHandler.prepare() calls self.format(record) which
        converts record.msg to a formatted string. This breaks ProcessorFormatter
        which expects record.msg to be a dict (from wrap_for_formatter).

        We preserve the record as-is so handlers can format it themselves.
        We also preserve exc_info so handlers can access exception details.
        """
        # Don't call self.format(record) - let handlers do their own formatting
        # Preserve exc_info for handlers (ProcessorFormatter needs it)
        return record

    def enqueue(self, record: logging.LogRecord) -> None:
        """
        Put record on queue, dropping if full.

        Periodically writes drop count to stderr (rate limited).
        """
        global _total_drop_count, _last_drop_warning_time

        try:
            self.queue.put_nowait(record)
        except queue.Full:
            # Update drop counts (thread-safe)
            with _drop_stats_lock:
                _total_drop_count += 1
                self._instance_drop_count += 1
                current_drop_count = _total_drop_count

            # Rate-limit drop warnings to stderr
            import time

            now = time.time()
            with _drop_stats_lock:
                if now - _last_drop_warning_time > DROP_WARNING_INTERVAL_SECONDS:
                    try:
                        print(
                            f"[WARN] Log queue full, dropped {current_drop_count} messages",
                            file=sys.__stderr__,
                        )
                    except Exception:
                        pass
                    _last_drop_warning_time = now


def get_drop_count() -> int:
    """
    Get total number of dropped log messages across all handlers.

    Returns:
        Total drop count (module-level aggregate)
    """
    with _drop_stats_lock:
        return _total_drop_count


# =============================================================================
# CRASH HOOKS
# =============================================================================


def _uncaught_exception_handler(exc_type, exc_value, exc_tb):
    """Handle uncaught exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # Use structlog logger
    logger = structlog.get_logger("crash")
    logger.critical(
        "uncaught_exception",
        category="unexpected",
        error_type=exc_type.__name__,
        message=str(exc_value),
        traceback="".join(traceback.format_exception(exc_type, exc_value, exc_tb))[
            :MAX_TRACEBACK_LENGTH
        ],
    )

    # Ensure logs are flushed
    _flush_logs()


def _thread_exception_handler(args):
    """Handle uncaught thread exceptions."""
    logger = structlog.get_logger("crash")
    logger.critical(
        "thread_exception",
        category="unexpected",
        error_type=args.exc_type.__name__,
        message=str(args.exc_value),
        thread_name=args.thread.name if args.thread else "unknown",
        traceback="".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )[:MAX_TRACEBACK_LENGTH],
    )


def _asyncio_exception_handler(loop, context):
    """
    Handle asyncio exceptions (unhandled Task exceptions).

    This captures exceptions from background tasks that weren't awaited
    or had their exceptions ignored.
    """
    from .error_store import ErrorCategory, get_error_store

    exception = context.get("exception")
    message = context.get("message", "Unknown asyncio error")

    # Build log data
    log_data = {
        "category": ErrorCategory.UNEXPECTED,
        "message": message,
    }

    error_type = "AsyncioError"
    tb_str = None

    if exception:
        error_type = type(exception).__name__
        log_data["error_type"] = error_type
        tb_str = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )[:MAX_TRACEBACK_LENGTH]
        log_data["traceback"] = tb_str

        # Classify timeout exceptions
        exc_name = error_type.lower()
        if "timeout" in exc_name:
            log_data["category"] = ErrorCategory.PROVIDER_TIMEOUT

    # Get task info if available
    if "future" in context:
        future = context["future"]
        log_data["task_name"] = getattr(future, "get_name", lambda: str(future))()

    # Record to error store directly (non-blocking)
    try:
        store = get_error_store()
        store.record_from_dict(
            level="ERROR",
            category=log_data["category"],
            error_type=error_type,
            message=message,
            traceback=tb_str,
            component="asyncio",
            operation="task_exception",
        )
    except Exception:
        # Don't fail if error store is unavailable
        pass

    # Also emit structured log
    logger = structlog.get_logger("asyncio")
    logger.error("task_exception", **log_data)


def _flush_logs():
    """Flush all pending logs (QueueListener + SQLite handlers)."""
    global _queue_listener, _sqlite_handler, _sqlite_log_handler, _shutting_down

    if _shutting_down:
        return  # Prevent recursive shutdown
    _shutting_down = True

    # 1. Stop QueueListener (flushes pending log records)
    if _queue_listener:
        try:
            _queue_listener.stop()
        except Exception:
            pass

    # 2. Flush SQLite error handler queue
    if _sqlite_handler:
        try:
            _sqlite_handler.close()
        except Exception:
            pass

    # 3. Flush SQLite log handler queue
    if _sqlite_log_handler:
        try:
            _sqlite_log_handler.close()
        except Exception:
            pass


def _signal_handler(signum, frame):
    """
    Handle SIGINT/SIGTERM signals for graceful shutdown.

    Flushes logs before exiting. Re-raises the signal after cleanup
    to allow normal shutdown behavior (e.g., KeyboardInterrupt for SIGINT,
    proper termination tracking by process managers for SIGTERM).
    """
    global _original_sigint_handler, _original_sigterm_handler

    # Flush logs first
    _flush_logs()

    # Re-install original handler and re-raise
    if signum == signal.SIGINT:
        signal.signal(signal.SIGINT, _original_sigint_handler or signal.SIG_DFL)
        raise KeyboardInterrupt
    elif signum == signal.SIGTERM:
        signal.signal(signal.SIGTERM, _original_sigterm_handler or signal.SIG_DFL)
        # Re-raise SIGTERM to allow proper process termination tracking
        # by process managers (systemd, supervisor, etc.)
        # On Unix: os.kill re-raises the signal with original handler
        # On Windows: SIGTERM exists but can only be sent internally, fallback to sys.exit
        import os

        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except (OSError, AttributeError):
            # Fallback for Windows or if os.kill fails
            sys.exit(0)


def _install_crash_hooks():
    """Install crash-safe exception handlers and signal handlers."""
    global _original_sigint_handler, _original_sigterm_handler

    # Uncaught exceptions
    sys.excepthook = _uncaught_exception_handler

    # Thread exceptions (Python 3.8+)
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_exception_handler

    # Signal handlers for graceful shutdown (SIGINT = Ctrl+C, SIGTERM = kill)
    try:
        _original_sigint_handler = signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError):
        pass  # Not in main thread or signal not available

    # SIGTERM only exists on Unix, but signal module handles this gracefully
    if hasattr(signal, "SIGTERM"):
        try:
            _original_sigterm_handler = signal.signal(signal.SIGTERM, _signal_handler)
        except (ValueError, OSError):
            pass  # Not in main thread

    # Register atexit handler for graceful shutdown
    atexit.register(_flush_logs)


# =============================================================================
# MAIN CONFIGURATION
# =============================================================================


def configure_logging(
    mode: Literal["cli", "tui"] = "cli",
    log_level: str | None = None,
    log_dir: str = ".claraity/logs",
    max_bytes: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 5,
) -> None:
    """
    Configure production-grade logging infrastructure.

    All logs go to JSONL file only - NO console output in any mode.
    Console is reserved for user-facing messages via Rich console.print().

    Configuration is loaded from `.claraity/config.yaml` with layered overrides:
        Environment variables > CLI flags > config.yaml > code defaults

    Args:
        mode: "cli" or "tui" (both behave the same - file-only logging)
        log_level: Override log level from CLI (default: from config.yaml or INFO)
        log_dir: Directory for log files
        max_bytes: Max size per log file before rotation
        backup_count: Number of rotated files to keep
    """
    global _queue_listener, _log_queue, _sqlite_handler, _sqlite_log_handler, _configured

    if _configured:
        return

    # Generate and bind run_id (process-level identifier)
    process_run_id = str(uuid.uuid4())[:12]
    run_id.set(process_run_id)

    # ---- Load centralized config from .claraity/config.yaml ----
    from .log_config_loader import (
        apply_component_levels,
        generate_default_config,
        load_logging_config,
        resolve_logging_config,
    )

    # Generate default config on first run
    generate_default_config()

    # Load and resolve with priority layering
    config = load_logging_config()
    env_level = os.environ.get("LOG_LEVEL")
    config = resolve_logging_config(
        env_level=env_level,
        cli_level=log_level,
        config=config,
    )

    # Resolved global level
    level = getattr(logging, config.level.upper(), logging.INFO)

    # Use retention settings from config for JSONL handler
    max_bytes = config.retention.jsonl_max_bytes
    backup_count = config.retention.jsonl_backup_count

    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Set restrictive permissions on the log directory (700 on POSIX)
    # NOTE: We inline the chmod call here instead of importing from
    # src.security.file_permissions to avoid a circular import:
    #   file_permissions -> get_logger -> configure_logging -> file_permissions
    if platform.system() != "Windows":
        try:
            import stat as _stat

            log_path.chmod(_stat.S_IRWXU)  # 700: owner rwx only
        except OSError:
            pass  # Best-effort, non-fatal

    # Create handlers list
    handlers = []

    # 1. Rotating file handler for JSONL (always enabled)
    jsonl_file = log_path / "app.jsonl"
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(jsonl_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(create_json_formatter())
    # Handler level from config (default: INFO)
    file_handler.setLevel(getattr(logging, config.handlers.jsonl_level, logging.INFO))
    handlers.append(file_handler)

    # 2. Console handler - DISABLED for both modes
    # All logs go to JSONL file only. Console output is reserved for:
    # - Rich console.print() for user-facing messages
    # - Actual application output
    # Log messages should never appear in user's terminal.
    # This also eliminates the "race condition" where module-level get_logger()
    # calls would auto-configure logging before the mode was known.

    # 3. SQLite error handler (always enabled)
    try:
        from .sqlite_error_handler import SQLiteErrorHandler

        sqlite_handler = SQLiteErrorHandler()
        # Handler level from config (default: ERROR)
        sqlite_handler.setLevel(getattr(logging, config.handlers.errors_db_level, logging.ERROR))
        handlers.append(sqlite_handler)
        _sqlite_handler = sqlite_handler  # Save reference for shutdown
    except ImportError:
        pass  # SQLite handler not available yet

    # 4. SQLite log handler - ALL log levels to logs.db for queryable access
    try:
        from .sqlite_log_handler import SQLiteLogHandler

        log_handler = SQLiteLogHandler()
        # Handler level from config (default: DEBUG)
        log_handler.setLevel(getattr(logging, config.handlers.logs_db_level, logging.DEBUG))
        handlers.append(log_handler)
        _sqlite_log_handler = log_handler  # Save reference for shutdown
    except ImportError:
        pass  # SQLite log handler not available yet

    # Create bounded queue for non-blocking logging (drops when full)
    _log_queue = queue.Queue(maxsize=LOG_QUEUE_SIZE)
    queue_handler = BoundedQueueHandler(_log_queue)

    # Configure root logger
    # INFO level for development - prevents DEBUG messages from flooding the queue
    # Set LOG_LEVEL=DEBUG env var if you need debug logs for troubleshooting
    root_logger = logging.getLogger()
    root_logger.setLevel(level)  # Use configured level (default: INFO)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add queue handler (only handler on root logger)
    root_logger.addHandler(queue_handler)

    # Start queue listener with all handlers
    _queue_listener = logging.handlers.QueueListener(
        _log_queue,
        *handlers,
        respect_handler_level=True,
    )
    _queue_listener.start()

    # ==========================================================================
    # STRUCTLOG CONFIGURATION
    # ==========================================================================
    #
    # Configure structlog to:
    # 1. Merge context variables
    # 2. Add log level
    # 3. Add timestamp
    # 4. Add caller info
    # 5. Inject context from contextvars
    # 6. Redact sensitive data
    # 7. Format exceptions
    # 8. Wrap for ProcessorFormatter (keeps event_dict as dict on record.msg)
    # 9. Pass to stdlib logger (which routes to QueueHandler)
    #
    # NOTE: We use ProcessorFormatter.wrap_for_formatter() instead of JSONRenderer()
    # so that handlers (especially SQLiteErrorHandler) can access the structured
    # event_dict directly from record.msg, rather than parsing JSON strings.
    #
    structlog.configure(
        processors=[
            # Merge context from contextvars
            structlog.contextvars.merge_contextvars,
            # Filter by log level early
            structlog.stdlib.filter_by_level,
            # Add log level
            structlog.stdlib.add_log_level,
            # Add logger name
            structlog.stdlib.add_logger_name,
            # Add timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # Add caller info
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                ]
            ),
            # Inject context from our contextvars
            add_context,
            # Redact sensitive data
            redact_sensitive,
            # Format exceptions
            structlog.processors.format_exc_info,
            # Stack info
            structlog.processors.StackInfoRenderer(),
            # Prepare for stdlib
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Unicode decode
            structlog.processors.UnicodeDecoder(),
            # Wrap for ProcessorFormatter - keeps event_dict as dict on record.msg
            # Handlers use ProcessorFormatter to do final rendering (JSON, console, etc.)
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Suppress noisy third-party loggers
    # These libraries generate excessive DEBUG/INFO logs during streaming/HTTP operations
    # which can flood the log queue (10,000 items) and cause message drops
    noisy_loggers = [
        "httpx",
        "httpcore",
        "openai",
        "multilspy",
        "urllib3",
        "asyncio",
        "hpack",
        "h2",
        # LiteLLM generates DEBUG logs per streaming chunk - extremely noisy
        "litellm",
        "LiteLLM",
        "litellm.proxy",
        "litellm.llms",
        "litellm.router",
        "litellm.caching",
        # markdown-it-py emits DEBUG logs per parser state transition
        # Incremental streaming triggers repeated re-parses, flooding the queue
        "markdown_it",
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Apply per-component log levels from config.yaml
    if config.components:
        apply_component_levels(config.components)

    # Install crash hooks
    _install_crash_hooks()

    _configured = True

    # Startup cleanup using retention config
    try:
        from .log_store import get_log_store

        get_log_store().clear_old(days=config.retention.logs_db_days)
    except Exception:
        pass  # Non-critical, logs.db may not exist yet

    # Log startup (this now goes through the full pipeline)
    logger = structlog.get_logger("logging")
    logger.info(
        "logging_configured",
        run_id=process_run_id,
        mode=mode,
        level=config.level,
        log_file=str(jsonl_file),
        max_bytes=max_bytes,
        backup_count=backup_count,
        config_components=config.components or None,
    )


# =============================================================================
# CONTEXT BINDING UTILITIES
# =============================================================================


def bind_context(
    run: str | None = None,
    session: str | None = None,
    request: str | None = None,
    turn: int | None = None,
    comp: str | None = None,
    op: str | None = None,
) -> None:
    """
    Bind context variables for logging correlation.

    Args:
        run: Run ID (process-level, set once at startup)
        session: Session ID
        request: Request ID (unique per request)
        turn: Turn ID (incremented per user message, stable within a turn)
        comp: Component name (e.g., 'core.agent', 'llm.openai')
        op: Operation name (e.g., 'stream_response', 'execute_tool')
    """
    if run is not None:
        run_id.set(run)
    if session is not None:
        session_id.set(session)
    if request is not None:
        request_id.set(request)
    if turn is not None:
        turn_id.set(turn)
    if comp is not None:
        component.set(comp)
    if op is not None:
        operation.set(op)


def clear_context() -> None:
    """Clear all context variables (except run_id which is process-level)."""
    session_id.set("")
    request_id.set("")
    turn_id.set(0)
    component.set("")
    operation.set("")
    # Note: run_id is intentionally NOT cleared as it's process-level


def new_request_id() -> str:
    """Generate a new request ID and bind it."""
    rid = str(uuid.uuid4())[:8]
    request_id.set(rid)
    return rid


# =============================================================================
# LOGGER FACTORY
# =============================================================================


def get_logger(name: str = None) -> BoundLogger:
    """
    Get a structlog bound logger with the given name.

    Usage:
        logger = get_logger("core.agent")
        logger.info("stream_started", model="gpt-4", iteration=1)
        logger.error("provider_timeout", elapsed_ms=60000, category="provider_timeout")
        logger.exception("unexpected_error")  # Includes traceback automatically

    Args:
        name: Logger name (defaults to calling module)

    Returns:
        structlog BoundLogger that routes through stdlib -> QueueHandler -> handlers
    """
    if not _configured:
        configure_logging()

    return structlog.get_logger(name)


# =============================================================================
# ASYNCIO EXCEPTION HANDLER INSTALLER
# =============================================================================


def install_asyncio_handler(loop=None) -> None:
    """
    Install asyncio exception handler on the given event loop.

    Should be called after creating the event loop but before running tasks.
    Captures unhandled Task exceptions and records them to error store + logs.

    Args:
        loop: Event loop (default: current running loop)
    """
    import asyncio

    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

    loop.set_exception_handler(_asyncio_exception_handler)
