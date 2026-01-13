"""
Instrumentation decorators for all subsystems.

Provides decorators to instrument agent methods, tool executions, and LLM calls
with Langfuse observability. Handles graceful degradation if Langfuse is not available.

Engineering Principles:
- No emojis in code (Windows cp1252 compatibility)
- Graceful degradation (works without Langfuse)
- Zero overhead when observability disabled
- Production-grade error handling

Note: Uses Langfuse v3 API (released June 2025)
"""

import time
import logging
from functools import wraps
from typing import Callable, Any, Optional, Dict

from src.observability.langfuse_config import (
    LANGFUSE_AVAILABLE,
    is_observability_enabled,
)

logger = logging.getLogger(__name__)

# Import Langfuse v3 observe decorator if available
if LANGFUSE_AVAILABLE:
    try:
        from langfuse import observe as _langfuse_observe, get_client
    except ImportError:
        _langfuse_observe = None
        get_client = None
else:
    _langfuse_observe = None
    get_client = None


def observe_agent_method(name: str, capture_input: bool = True, capture_output: bool = True):
    """
    Decorator for agent methods (high-level operations) using Langfuse v3 API.

    Traces agent-level operations like autonomous_execution, task_decomposition.

    Args:
        name: Human-readable name for the operation
        capture_input: Whether to capture input arguments
        capture_output: Whether to capture output

    Usage:
        @observe_agent_method("autonomous_execution")
        def execute_autonomous(self, task: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Skip if observability disabled or Langfuse not available
        if not is_observability_enabled() or not LANGFUSE_AVAILABLE or not _langfuse_observe:
            return func

        # Apply Langfuse v3 @observe decorator
        try:
            decorated = _langfuse_observe(
                name=name,
                as_type="span",  # Agent methods are spans (not generations)
                capture_input=capture_input,
                capture_output=capture_output
            )(func)

            # Preserve function metadata (if Langfuse doesn't do it)
            @wraps(func)
            def wrapper(*args, **kwargs):
                return decorated(*args, **kwargs)

            # Langfuse @observe already captures duration, input, output, and errors
            # No need for additional metadata updates (they fail due to context issues)
            return wrapper

        except Exception as e:
            logger.warning(f"Failed to apply Langfuse decorator: {e}")
            return func

    return decorator


def observe_tool_execution(tool_name: str, capture_args: bool = True):
    """
    Decorator for tool execution (file ops, git, bash, etc.) using Langfuse v3 API.

    Traces individual tool calls with detailed input/output.

    Args:
        tool_name: Name of the tool (e.g., "write_file", "run_command")
        capture_args: Whether to capture input arguments

    Usage:
        @observe_tool_execution("write_file")
        def write_file(file_path: str, content: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Skip if observability disabled or Langfuse not available
        if not is_observability_enabled() or not LANGFUSE_AVAILABLE or not _langfuse_observe:
            return func

        # Apply Langfuse v3 @observe decorator with tool type
        try:
            decorated = _langfuse_observe(
                name=tool_name,
                as_type="tool",  # Tool execution
                capture_input=capture_args,
                capture_output=True
            )(func)

            # Preserve function metadata (if Langfuse doesn't do it)
            @wraps(func)
            def wrapper(*args, **kwargs):
                return decorated(*args, **kwargs)

            # Langfuse @observe already captures duration, input, output, and errors
            return wrapper

        except Exception as e:
            logger.warning(f"Failed to apply Langfuse tool decorator: {e}")
            return func

    return decorator


def observe_llm_call(model_name: Optional[str] = None):
    """
    Decorator for LLM API calls using Langfuse v3 API.

    Traces LLM calls with automatic cost calculation (via Langfuse).

    Args:
        model_name: LLM model name (for cost calculation)

    Usage:
        @observe_llm_call(model_name="gpt-4")
        def call_llm(self, messages: list):
            ...

    Note: Response should have .usage attribute with prompt_tokens and completion_tokens
    """
    def decorator(func: Callable) -> Callable:
        # Skip if observability disabled or Langfuse not available
        if not is_observability_enabled() or not LANGFUSE_AVAILABLE or not _langfuse_observe:
            return func

        # Apply Langfuse v3 @observe decorator with generation type
        try:
            decorated = _langfuse_observe(
                name="llm_call",
                as_type="generation",  # LLM calls are generations
                capture_input=True,
                capture_output=True
            )(func)

            # Preserve function metadata (if Langfuse doesn't do it)
            @wraps(func)
            def wrapper(*args, **kwargs):
                return decorated(*args, **kwargs)

            # Langfuse @observe already captures duration, input, output, errors, and token usage
            return wrapper

        except Exception as e:
            logger.warning(f"Failed to apply Langfuse LLM decorator: {e}")
            return func

    return decorator


def start_trace(name: str, user_id: Optional[str] = None, session_id: Optional[str] = None, tags: Optional[list] = None):
    """
    Manually start a trace (for top-level operations) using Langfuse v3 API.

    Note: This creates a trace without a context manager for manual control.
    The trace will remain active until explicitly ended or application exit.
    For automatic lifecycle management, use trace_context() instead.

    Args:
        name: Trace name
        user_id: User identifier
        session_id: Session identifier
        tags: List of tags for filtering

    Returns:
        Trace ID (for linking child operations) or None if observability disabled
    """
    if not is_observability_enabled() or not LANGFUSE_AVAILABLE or not get_client:
        return None

    try:
        langfuse = get_client()

        # Create trace directly (not via context manager for manual control)
        trace = langfuse.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            tags=tags or []
        )

        return trace.id

    except Exception as e:
        logger.warning(f"Failed to start trace: {e}")
        return None


def update_trace(output: Optional[Dict] = None, metadata: Optional[Dict] = None):
    """
    Update the current trace with output/metadata using Langfuse v3 API.

    Args:
        output: Output data to record
        metadata: Metadata to attach
    """
    if not is_observability_enabled() or not LANGFUSE_AVAILABLE or not get_client:
        return

    try:
        langfuse = get_client()

        # Get current span and update trace
        update_data = {}
        if output:
            update_data["output"] = output
        if metadata:
            update_data["metadata"] = metadata

        # Update via current span
        langfuse.update_current_span(**update_data)

    except Exception as e:
        logger.warning(f"Failed to update trace: {e}")


def flush_observations():
    """
    Flush all pending observations to Langfuse (call at shutdown).
    """
    if not LANGFUSE_AVAILABLE or not get_client:
        return

    try:
        langfuse = get_client()
        langfuse.flush()
        logger.info("[OK] Flushed observations to Langfuse")
    except Exception as e:
        logger.warning(f"Failed to flush observations: {e}")
