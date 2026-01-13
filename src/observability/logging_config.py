"""
Production-grade logging configuration with structlog + stdlib.

Architecture:
- structlog: Context binding, JSON formatting, key=value logging
- stdlib: Transport layer (handlers, rotation, queueing)
- QueueHandler/QueueListener: Non-blocking I/O for async safety

Flow:
    structlog.get_logger() -> stdlib Logger -> QueueHandler -> QueueListener
                                                                    |
                                         +-------------+------------+------------+
                                         |             |            |            |
                                   RotatingFile   StreamHandler  SQLiteError   (TUI: stderr only)
                                   (JSONL)        (CLI only)     Handler

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
from typing import Any, Dict, Literal, Optional

import structlog
from structlog.stdlib import BoundLogger

# =============================================================================
# CONTEXT VARIABLES (for async propagation)
# =============================================================================

run_id: ContextVar[str] = ContextVar('run_id', default='')  # Process-level ID, set once at startup
session_id: ContextVar[str] = ContextVar('session_id', default='')
stream_id: ContextVar[str] = ContextVar('stream_id', default='')
request_id: ContextVar[str] = ContextVar('request_id', default='')
component: ContextVar[str] = ContextVar('component', default='')
operation: ContextVar[str] = ContextVar('operation', default='')

# =============================================================================
# GLOBALS
# =============================================================================

_queue_listener: Optional[logging.handlers.QueueListener] = None
_log_queue: Optional[queue.Queue] = None
_sqlite_handler: Optional["SQLiteErrorHandler"] = None  # Forward reference
_configured: bool = False
_shutting_down: bool = False
_original_sigint_handler = None
_original_sigterm_handler = None

# =============================================================================
# REDACTION
# =============================================================================

# Patterns to redact (compiled for performance)
_REDACT_PATTERNS = [
    (re.compile(r'(api[_-]?key|apikey|authorization|auth[_-]?token|bearer|secret|password|passwd|pwd)\s*[=:]\s*["\']?[\w\-\.]+["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})', re.IGNORECASE), '***API_KEY***'),
    (re.compile(r'(Bearer\s+[\w\-\.]+)', re.IGNORECASE), 'Bearer ***REDACTED***'),
]

# Keys to fully redact in dicts
_REDACT_KEYS = {'api_key', 'apikey', 'api-key', 'authorization', 'auth_token', 'secret', 'password', 'passwd', 'pwd', 'bearer'}


def _redact_value(value: Any, max_length: int = 500) -> Any:
    """Redact sensitive values and truncate long strings."""
    if isinstance(value, str):
        # Truncate long strings (like prompts)
        if len(value) > max_length:
            value = value[:max_length] + f'...[truncated {len(value) - max_length} chars]'
        # Apply redaction patterns
        for pattern, replacement in _REDACT_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    elif isinstance(value, dict):
        return _redact_dict(value, max_length)
    elif isinstance(value, (list, tuple)):
        return [_redact_value(v, max_length) for v in value[:10]]  # Limit list length
    return value


def _redact_dict(d: Dict[str, Any], max_length: int = 500) -> Dict[str, Any]:
    """Recursively redact sensitive keys in dictionaries."""
    result = {}
    for key, value in d.items():
        if key.lower() in _REDACT_KEYS:
            result[key] = '***REDACTED***'
        else:
            result[key] = _redact_value(value, max_length)
    return result


def redact_sensitive(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Structlog processor to redact sensitive information."""
    return _redact_dict(event_dict)


# =============================================================================
# CONTEXT INJECTION (structlog processor)
# =============================================================================

def add_context(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Structlog processor to inject context variables."""
    ctx_run = run_id.get()
    ctx_session = session_id.get()
    ctx_stream = stream_id.get()
    ctx_request = request_id.get()
    ctx_component = component.get()
    ctx_operation = operation.get()

    if ctx_run:
        event_dict['run_id'] = ctx_run
    if ctx_session:
        event_dict['session_id'] = ctx_session
    if ctx_stream:
        event_dict['stream_id'] = ctx_stream
    if ctx_request:
        event_dict['request_id'] = ctx_request
    if ctx_component:
        event_dict['component'] = ctx_component
    if ctx_operation:
        event_dict['operation'] = ctx_operation

    return event_dict


# =============================================================================
# CUSTOM FORMATTER FOR JSONL OUTPUT
# =============================================================================

class StructlogJSONFormatter(logging.Formatter):
    """
    JSON formatter that extracts structlog event dict from LogRecord.

    structlog.stdlib puts the pre-rendered message in record.msg.
    We need to extract structured data and format as clean JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON line."""
        # Check if this is a structlog message (contains JSON-like content)
        msg = record.getMessage()

        # Base entry with timestamp
        log_entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
        }

        # Try to extract structlog event dict
        if hasattr(record, '_structlog_event_dict'):
            event_dict = record._structlog_event_dict
            if isinstance(event_dict, dict):
                for key, value in event_dict.items():
                    if key == 'event':
                        log_entry['event'] = value
                    elif key not in ('_logger', '_record', 'level', 'logger', 'timestamp'):
                        log_entry[key] = value
        else:
            # Check if message is JSON (from structlog JSONRenderer)
            if msg.startswith('{') and msg.endswith('}'):
                try:
                    parsed = json.loads(msg)
                    if isinstance(parsed, dict):
                        for key, value in parsed.items():
                            if key == 'event':
                                log_entry['event'] = value
                            elif key not in ('level', 'logger', 'timestamp'):
                                log_entry[key] = value
                except json.JSONDecodeError:
                    log_entry['event'] = msg
            else:
                log_entry['event'] = msg

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            log_entry['exception'] = {
                'type': exc_type.__name__ if exc_type else 'Unknown',
                'message': str(exc_value) if exc_value else '',
                'traceback': self.formatException(record.exc_info)[:32768],
            }

        # Add source location
        log_entry['source'] = {
            'file': record.filename,
            'line': record.lineno,
            'function': record.funcName,
        }

        return json.dumps(log_entry, default=str, ensure_ascii=False)


# =============================================================================
# SIMPLE CONSOLE FORMATTER
# =============================================================================

class StructlogConsoleFormatter(logging.Formatter):
    """Simple console formatter that shows structlog events nicely."""

    def format(self, record: logging.LogRecord) -> str:
        """Format for console output."""
        msg = record.getMessage()

        # If it's JSON from structlog, parse and format nicely
        if msg.startswith('{') and msg.endswith('}'):
            try:
                parsed = json.loads(msg)
                event = parsed.get('event', msg)
                return f"[{record.levelname}] {record.name}: {event}"
            except json.JSONDecodeError:
                pass

        return f"[{record.levelname}] {record.name}: {msg}"


# =============================================================================
# BOUNDED QUEUE HANDLER (with drop policy)
# =============================================================================

class BoundedQueueHandler(logging.handlers.QueueHandler):
    """
    QueueHandler that drops messages when queue is full instead of blocking.

    This prevents log producers from being blocked by slow consumers,
    which is critical for non-blocking async code.
    """

    _drop_count: int = 0
    _last_drop_warning: float = 0.0

    def enqueue(self, record: logging.LogRecord) -> None:
        """
        Put record on queue, dropping if full.

        Periodically writes drop count to stderr (at most every 10 seconds).
        """
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            BoundedQueueHandler._drop_count += 1
            # Rate-limit drop warnings to stderr
            import time
            now = time.time()
            if now - BoundedQueueHandler._last_drop_warning > 10.0:
                try:
                    print(
                        f"[WARN] Log queue full, dropped {BoundedQueueHandler._drop_count} messages",
                        file=sys.__stderr__,
                    )
                except Exception:
                    pass
                BoundedQueueHandler._last_drop_warning = now


# =============================================================================
# CRASH HOOKS
# =============================================================================

def _uncaught_exception_handler(exc_type, exc_value, exc_tb):
    """Handle uncaught exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # Use structlog logger
    logger = structlog.get_logger('crash')
    logger.critical(
        'uncaught_exception',
        category='unexpected',
        error_type=exc_type.__name__,
        message=str(exc_value),
        traceback=''.join(traceback.format_exception(exc_type, exc_value, exc_tb))[:32768],
    )

    # Ensure logs are flushed
    _flush_logs()


def _thread_exception_handler(args):
    """Handle uncaught thread exceptions."""
    logger = structlog.get_logger('crash')
    logger.critical(
        'thread_exception',
        category='unexpected',
        error_type=args.exc_type.__name__,
        message=str(args.exc_value),
        thread_name=args.thread.name if args.thread else 'unknown',
        traceback=''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))[:32768],
    )


def _asyncio_exception_handler(loop, context):
    """
    Handle asyncio exceptions (unhandled Task exceptions).

    This captures exceptions from background tasks that weren't awaited
    or had their exceptions ignored.
    """
    from .error_store import get_error_store, ErrorCategory

    exception = context.get('exception')
    message = context.get('message', 'Unknown asyncio error')

    # Build log data
    log_data = {
        'category': ErrorCategory.UNEXPECTED,
        'message': message,
    }

    error_type = 'AsyncioError'
    tb_str = None

    if exception:
        error_type = type(exception).__name__
        log_data['error_type'] = error_type
        tb_str = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))[:32768]
        log_data['traceback'] = tb_str

        # Classify timeout exceptions
        exc_name = error_type.lower()
        if 'timeout' in exc_name:
            log_data['category'] = ErrorCategory.PROVIDER_TIMEOUT

    # Get task info if available
    if 'future' in context:
        future = context['future']
        log_data['task_name'] = getattr(future, 'get_name', lambda: str(future))()

    # Record to error store directly (non-blocking)
    try:
        store = get_error_store()
        store.record_from_dict(
            level='ERROR',
            category=log_data['category'],
            error_type=error_type,
            message=message,
            traceback=tb_str,
            component='asyncio',
            operation='task_exception',
        )
    except Exception:
        # Don't fail if error store is unavailable
        pass

    # Also emit structured log
    logger = structlog.get_logger('asyncio')
    logger.error('task_exception', **log_data)


def _flush_logs():
    """Flush all pending logs (QueueListener + SQLite handler)."""
    global _queue_listener, _sqlite_handler, _shutting_down

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


def _signal_handler(signum, frame):
    """
    Handle SIGINT/SIGTERM signals for graceful shutdown.

    Flushes logs before exiting. Re-raises the signal after cleanup
    to allow normal shutdown behavior (e.g., KeyboardInterrupt).
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
        # On Windows SIGTERM doesn't exist, but handle gracefully
        sys.exit(0)


def _install_crash_hooks():
    """Install crash-safe exception handlers and signal handlers."""
    global _original_sigint_handler, _original_sigterm_handler

    # Uncaught exceptions
    sys.excepthook = _uncaught_exception_handler

    # Thread exceptions (Python 3.8+)
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _thread_exception_handler

    # Signal handlers for graceful shutdown (SIGINT = Ctrl+C, SIGTERM = kill)
    try:
        _original_sigint_handler = signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError):
        pass  # Not in main thread or signal not available

    # SIGTERM only exists on Unix, but signal module handles this gracefully
    if hasattr(signal, 'SIGTERM'):
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
    log_level: Optional[str] = None,
    log_dir: str = ".clarity/logs",
    max_bytes: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 5,
) -> None:
    """
    Configure production-grade logging infrastructure.

    Args:
        mode: "cli" for console+file, "tui" for file-only (WARN+ to stderr)
        log_level: Override log level (default: from LOG_LEVEL env or INFO)
        log_dir: Directory for log files
        max_bytes: Max size per log file before rotation
        backup_count: Number of rotated files to keep
    """
    global _queue_listener, _log_queue, _sqlite_handler, _configured

    if _configured:
        return

    # Generate and bind run_id (process-level identifier)
    process_run_id = str(uuid.uuid4())[:12]
    run_id.set(process_run_id)

    # Get log level
    if log_level is None:
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Create handlers list
    handlers = []

    # 1. Rotating file handler for JSONL (always enabled)
    jsonl_file = log_path / 'app.jsonl'
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(jsonl_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
    )
    file_handler.setFormatter(StructlogJSONFormatter())
    file_handler.setLevel(logging.DEBUG)  # Capture all levels to file
    handlers.append(file_handler)

    # 2. Console/stderr handler based on mode
    if mode == "cli":
        # CLI mode: console output at configured level
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(StructlogConsoleFormatter())
        console_handler.setLevel(level)
        handlers.append(console_handler)
    elif mode == "tui":
        # TUI mode: WARN+ to stderr only (avoid interfering with TUI)
        stderr_handler = logging.StreamHandler(sys.__stderr__)
        stderr_handler.setFormatter(StructlogConsoleFormatter())
        stderr_handler.setLevel(logging.WARNING)
        handlers.append(stderr_handler)

    # 3. SQLite error handler (always enabled)
    try:
        from .sqlite_error_handler import SQLiteErrorHandler
        sqlite_handler = SQLiteErrorHandler()
        sqlite_handler.setLevel(logging.ERROR)
        handlers.append(sqlite_handler)
        _sqlite_handler = sqlite_handler  # Save reference for shutdown
    except ImportError:
        pass  # SQLite handler not available yet

    # Create bounded queue for non-blocking logging (drops when full)
    _log_queue = queue.Queue(maxsize=10000)
    queue_handler = BoundedQueueHandler(_log_queue)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all, let handlers filter

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
    # 8. Render to JSON string
    # 9. Pass to stdlib logger (which routes to QueueHandler)
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
            # Render to JSON string (this becomes the log message)
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Suppress noisy third-party loggers
    noisy_loggers = [
        'httpx', 'httpcore', 'openai', 'multilspy', 'chromadb',
        'urllib3', 'asyncio', 'hpack', 'h2',
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Install crash hooks
    _install_crash_hooks()

    _configured = True

    # Log startup (this now goes through the full pipeline)
    logger = structlog.get_logger('logging')
    logger.info(
        'logging_configured',
        run_id=process_run_id,
        mode=mode,
        level=log_level,
        log_file=str(jsonl_file),
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


# =============================================================================
# CONTEXT BINDING UTILITIES
# =============================================================================

def bind_context(
    run: Optional[str] = None,
    session: Optional[str] = None,
    stream: Optional[str] = None,
    request: Optional[str] = None,
    comp: Optional[str] = None,
    op: Optional[str] = None,
) -> None:
    """
    Bind context variables for logging correlation.

    Args:
        run: Run ID (process-level, set once at startup)
        session: Session ID
        stream: Stream ID (for streaming responses)
        request: Request ID (unique per request)
        comp: Component name (e.g., 'core.agent', 'llm.openai')
        op: Operation name (e.g., 'stream_response', 'execute_tool')
    """
    if run is not None:
        run_id.set(run)
    if session is not None:
        session_id.set(session)
    if stream is not None:
        stream_id.set(stream)
    if request is not None:
        request_id.set(request)
    if comp is not None:
        component.set(comp)
    if op is not None:
        operation.set(op)


def clear_context() -> None:
    """Clear all context variables (except run_id which is process-level)."""
    session_id.set('')
    stream_id.set('')
    request_id.set('')
    component.set('')
    operation.set('')
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
