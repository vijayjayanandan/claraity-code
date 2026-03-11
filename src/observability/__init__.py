"""
Observability Layer for AI Coding Agent

Production-grade observability using:
- Langfuse for LLM tracing
- structlog + stdlib for structured logging
- SQLite for metrics and error persistence

Usage:
    from src.observability import observe_agent_method, start_trace, metrics
    from src.observability import configure_logging, bind_context, get_logger

    # Configure logging (call once at startup)
    configure_logging(mode="cli")  # or "tui"

    # Get structured logger
    logger = get_logger("my_component")
    logger.info("event_name", key="value")

    # Bind context for correlation
    bind_context(session="abc123", operation="stream_response")

    # Instrument functions
    @observe_agent_method("generate_code")
    def generate_code(prompt: str):
        ...

    # Manual tracing
    trace_id = start_trace("autonomous_task", session_id="session123")

    # Record metrics
    record_llm_latency(150.0, "gpt-4")

    # Query errors
    from src.observability import get_error_store
    errors = get_error_store().query(session_id="abc123")

    # Query all logs for a session
    from src.observability import query_session_logs, query_session_errors
    logs = query_session_logs("session-id", level="error", limit=50)
    errors = query_session_errors("session-id")
"""

from .error_store import (
    ErrorCategory,
    ErrorRecord,
    ErrorStore,
    error_store,
    get_error_store,
)
from .instrumentation import (
    flush_observations,
    observe_agent_method,
    observe_llm_call,
    observe_tool_execution,
    start_trace,
    update_trace,
)
from .langfuse_config import (
    LANGFUSE_AVAILABLE,
    is_observability_enabled,
)
from .log_config_loader import (
    HandlerConfig,
    LoggingConfig,
    RetentionConfig,
    load_logging_config,
)
from .log_query import (
    query_session_errors,
    query_session_logs,
)
from .log_store import (
    LogRecord,
    LogStore,
    get_log_store,
    log_store,
)
from .logging_config import (
    bind_context,
    clear_context,
    component,
    configure_logging,
    get_logger,
    install_asyncio_handler,
    new_request_id,
    operation,
    request_id,
    # Context variables
    session_id,
    stream_id,
)
from .metrics import (
    cleanup_old_metrics,
    get_metrics_collector,
    get_session_stats,
    metrics,
    record_cost_estimate,
    record_llm_latency,
    record_token_usage,
)
from .metrics import (
    record_tool_execution as record_tool_metric,
)
from .transcript_logger import (
    TranscriptEvent,
    TranscriptLogger,
)

__all__ = [
    # Core
    "LANGFUSE_AVAILABLE",
    "is_observability_enabled",
    # Instrumentation (Langfuse v3 API)
    "observe_agent_method",
    "observe_tool_execution",
    "observe_llm_call",
    "start_trace",
    "update_trace",
    "flush_observations",
    # Metrics (SQLite-based)
    "metrics",
    "get_metrics_collector",
    "record_llm_latency",
    "record_token_usage",
    "record_tool_metric",
    "record_cost_estimate",
    "get_session_stats",
    "cleanup_old_metrics",
    # Logging (structlog + stdlib)
    "configure_logging",
    "bind_context",
    "clear_context",
    "new_request_id",
    "get_logger",
    "install_asyncio_handler",
    # Context variables
    "session_id",
    "stream_id",
    "request_id",
    "component",
    "operation",
    # Error Store (SQLite-based)
    "ErrorStore",
    "ErrorRecord",
    "ErrorCategory",
    "get_error_store",
    "error_store",
    # Log Store (SQLite-based, all log levels)
    "LogStore",
    "LogRecord",
    "get_log_store",
    "log_store",
    # Programmatic Query API
    "query_session_logs",
    "query_session_errors",
    # Logging Configuration
    "LoggingConfig",
    "HandlerConfig",
    "RetentionConfig",
    "load_logging_config",
    # Transcript Logger (JSONL-based)
    "TranscriptLogger",
    "TranscriptEvent",
]
