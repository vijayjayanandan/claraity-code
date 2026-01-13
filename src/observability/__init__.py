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
"""

from .langfuse_config import (
    LANGFUSE_AVAILABLE,
    is_observability_enabled,
)

from .instrumentation import (
    observe_agent_method,
    observe_tool_execution,
    observe_llm_call,
    start_trace,
    update_trace,
    flush_observations,
)

from .metrics import (
    metrics,
    get_metrics_collector,
    record_llm_latency,
    record_token_usage,
    record_tool_execution as record_tool_metric,
    record_cost_estimate,
    get_session_stats,
    cleanup_old_metrics,
)

from .logging_config import (
    configure_logging,
    bind_context,
    clear_context,
    new_request_id,
    get_logger,
    install_asyncio_handler,
    # Context variables
    session_id,
    stream_id,
    request_id,
    component,
    operation,
)

from .error_store import (
    ErrorStore,
    ErrorRecord,
    ErrorCategory,
    get_error_store,
    error_store,
)

__all__ = [
    # Core
    'LANGFUSE_AVAILABLE',
    'is_observability_enabled',

    # Instrumentation (Langfuse v3 API)
    'observe_agent_method',
    'observe_tool_execution',
    'observe_llm_call',
    'start_trace',
    'update_trace',
    'flush_observations',

    # Metrics (SQLite-based)
    'metrics',
    'get_metrics_collector',
    'record_llm_latency',
    'record_token_usage',
    'record_tool_metric',
    'record_cost_estimate',
    'get_session_stats',
    'cleanup_old_metrics',

    # Logging (structlog + stdlib)
    'configure_logging',
    'bind_context',
    'clear_context',
    'new_request_id',
    'get_logger',
    'install_asyncio_handler',
    # Context variables
    'session_id',
    'stream_id',
    'request_id',
    'component',
    'operation',

    # Error Store (SQLite-based)
    'ErrorStore',
    'ErrorRecord',
    'ErrorCategory',
    'get_error_store',
    'error_store',
]
