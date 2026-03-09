"""
Langfuse Configuration and Client Initialization

Provides the Langfuse client for production observability of the AI coding agent.
"""

import atexit
import logging
import os
from contextlib import contextmanager
from typing import Any, Optional

# Langfuse import with graceful degradation (v3 API - June 2025)
try:
    from langfuse import Langfuse, get_client, observe
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None
    get_client = None
    observe = None

logger = logging.getLogger(__name__)

# Global Langfuse client instance
_langfuse_client: "Langfuse | None" = None  # noqa: UP037 - Langfuse may be None at runtime
_current_trace = None


def _cleanup_langfuse():
    """Cleanup function to flush Langfuse events on exit."""
    global _langfuse_client
    if _langfuse_client:
        try:
            _langfuse_client.flush()
            logger.info("[OK] Langfuse client flushed on exit")
        except Exception as e:
            logger.error(f"Failed to flush Langfuse on exit: {e}")


def initialize_langfuse() -> Langfuse | None:
    """
    Initialize Langfuse client from environment variables.

    Environment variables:
        LANGFUSE_PUBLIC_KEY: Public API key
        LANGFUSE_SECRET_KEY: Secret API key
        LANGFUSE_HOST: Langfuse server URL (default: http://localhost:3000)
        OBSERVABILITY_ENABLED: Enable/disable observability (default: true)

    Returns:
        Langfuse client instance or None if disabled/unavailable
    """
    global _langfuse_client

    # Check if observability is disabled
    if os.getenv("OBSERVABILITY_ENABLED", "true").lower() == "false":
        logger.info("Observability disabled via OBSERVABILITY_ENABLED=false")
        return None

    # Check if Langfuse is installed (optional dependency)
    if not LANGFUSE_AVAILABLE:
        logger.debug("Langfuse not installed - observability tracing disabled")
        return None

    # Get configuration from environment
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

    # Use default keys for local development if not set
    if not public_key:
        public_key = "pk-lf-local-dev"
        logger.info("Using default local development public key")

    if not secret_key:
        secret_key = "sk-lf-local-dev"
        logger.info("Using default local development secret key")

    try:
        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host
        )

        # Register cleanup on exit to flush pending events
        atexit.register(_cleanup_langfuse)

        logger.info(f"[OK] Langfuse client initialized (host: {host})")
        return _langfuse_client

    except Exception as e:
        logger.error(f"Failed to initialize Langfuse: {e}")
        return None


def get_langfuse_client() -> Langfuse | None:
    """
    Get the global Langfuse client instance.

    Returns:
        Langfuse client or None if not initialized
    """
    global _langfuse_client

    if _langfuse_client is None:
        _langfuse_client = initialize_langfuse()

    return _langfuse_client


# Convenience alias
langfuse_client = get_langfuse_client


def is_enabled() -> bool:
    """
    Check if observability is enabled.

    Returns:
        True if Langfuse client is available and enabled
    """
    return get_langfuse_client() is not None


# Alias for consistency
is_observability_enabled = is_enabled


def start_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list | None = None
):
    """
    Start a new trace for tracking execution.

    Args:
        name: Trace name (e.g., "autonomous_task", "direct_mode_execution")
        user_id: Optional user identifier
        session_id: Optional session identifier
        metadata: Additional metadata to attach
        tags: List of tags for categorization

    Returns:
        Trace object or None if observability disabled
    """
    global _current_trace

    client = get_langfuse_client()
    if not client:
        return None

    try:
        _current_trace = client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
            tags=tags or []
        )
        logger.debug(f"Started trace: {name}")
        return _current_trace

    except Exception as e:
        logger.error(f"Failed to start trace: {e}")
        return None


def end_trace():
    """
    End the current trace.

    This is automatically called when traces are used as context managers,
    but can be called manually if needed.
    """
    global _current_trace

    if _current_trace:
        try:
            # Langfuse traces are automatically ended when flushed
            client = get_langfuse_client()
            if client:
                client.flush()
            logger.debug("Ended current trace")
        except Exception as e:
            logger.error(f"Failed to end trace: {e}")
        finally:
            _current_trace = None


def get_current_trace():
    """
    Get the current active trace.

    Returns:
        Current trace object or None
    """
    return _current_trace


@contextmanager
def trace_context(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list | None = None
):
    """
    Context manager for automatic trace lifecycle.

    Usage:
        with trace_context("my_task"):
            # Your code here
            pass

    Args:
        name: Trace name
        user_id: Optional user identifier
        session_id: Optional session identifier
        metadata: Additional metadata
        tags: List of tags
    """
    trace = start_trace(
        name=name,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
        tags=tags
    )

    try:
        yield trace
    finally:
        end_trace()


def flush():
    """
    Flush all pending events to Langfuse.

    Call this before application exit to ensure all data is sent.
    """
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
            logger.debug("Flushed Langfuse events")
        except Exception as e:
            logger.error(f"Failed to flush Langfuse: {e}")


# Initialize client on module import
_langfuse_client = initialize_langfuse()
