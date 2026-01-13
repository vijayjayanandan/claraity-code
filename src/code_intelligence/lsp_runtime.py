"""
LSP Runtime - Persistent event loop for LSP server reuse.

Provides a background thread with a dedicated asyncio event loop that hosts
a singleton LSPClientManager. This allows LSP servers to be reused across
multiple tool calls, avoiding the ~2.5s cold start penalty on each call.

Usage:
    from src.code_intelligence.lsp_runtime import lsp_run, get_manager_async

    # From sync code (main thread): submit coroutine to LSP loop
    result = lsp_run(some_async_func(), timeout=15.0)

    # From async code on LSP loop: get manager directly
    manager = await get_manager_async()
    symbols = await manager.request_document_symbols(file_path)

IMPORTANT:
    - Use get_manager_sync() ONLY from non-LSP threads
    - Use get_manager_async() from code running ON the LSP loop
    - Mixing these up will cause deadlocks!

TIMEOUT BEHAVIOR:
    - Timeouts are enforced INSIDE the loop via asyncio.wait_for()
    - On timeout, the coroutine is cancelled cleanly
    - NO automatic restart on timeout - that causes instability
    - Restart only happens if loop is truly dead (closed/thread dead)
"""

import asyncio
import atexit
import concurrent.futures
import logging
import threading
from typing import Any, Coroutine, Optional, TypeVar

from src.code_intelligence.lsp_client_manager import LSPClientManager

logger = logging.getLogger("code_intelligence.lsp_runtime")

T = TypeVar('T')

# Module-level state
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_manager: Optional[LSPClientManager] = None
_lock = threading.Lock()
_loop_ready = threading.Event()  # Signaled when loop is ready
_request_lock: Optional[asyncio.Lock] = None  # Serializes LSP requests


def _run_loop():
    """Background thread entry point - runs the event loop forever."""
    global _loop, _request_lock

    # Create new event loop for this thread
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    # Create request lock on this loop
    _request_lock = asyncio.Lock()

    # Signal that loop is ready
    _loop_ready.set()

    logger.info(f"LSP runtime started (loop_id={id(_loop)}, thread={threading.current_thread().name})")

    try:
        _loop.run_forever()
    finally:
        # Cleanup when loop stops
        try:
            _loop.run_until_complete(_loop.shutdown_asyncgens())
        except Exception as e:
            logger.warning(f"Error shutting down async generators: {e}")
        _loop.close()
        logger.info("LSP runtime stopped")


def _is_runtime_healthy() -> bool:
    """Check if the runtime is in a healthy state."""
    return (
        _thread is not None and
        _thread.is_alive() and
        _loop is not None and
        not _loop.is_closed()
    )


def _ensure_runtime():
    """Ensure background thread and loop are running and healthy."""
    global _thread, _loop, _request_lock, _manager

    with _lock:
        # Check if we need to (re)start the runtime
        needs_restart = not _is_runtime_healthy()

        if needs_restart:
            # CRITICAL: Clear ready signal FIRST to prevent stale reads
            # This ensures no caller sees a "ready" signal from a dead loop
            _loop_ready.clear()

            # Reset loop-affine state (MANDATORY)
            # Manager and request_lock are bound to the old loop - unsafe to reuse
            _manager = None
            _request_lock = None

            # Stop old thread gracefully if it exists and is still alive
            old_thread = _thread
            old_loop = _loop

            if old_thread is not None and old_thread.is_alive():
                # Try to stop the old loop gracefully
                if old_loop is not None and not old_loop.is_closed():
                    try:
                        old_loop.call_soon_threadsafe(old_loop.stop)
                    except Exception:
                        pass  # Loop may already be stopping

                # Wait for old thread to actually stop before starting new one
                # This prevents "two runtimes" condition
                old_thread.join(timeout=5.0)

                if old_thread.is_alive():
                    logger.warning(
                        "Old LSP runtime thread did not stop within 5s. "
                        "Proceeding with new runtime - may cause instability."
                    )

            # Clear old loop reference only after thread is stopped
            _loop = None

            # Start new thread
            _thread = threading.Thread(
                target=_run_loop,
                name="lsp-runtime",
                daemon=True  # Dies with main process
            )
            _thread.start()
            logger.info("LSP runtime (re)started")

    # Wait for loop to be ready (outside lock to avoid blocking)
    _loop_ready.wait(timeout=10.0)
    if not _loop_ready.is_set():
        raise RuntimeError("LSP runtime failed to start within 10s")


def get_manager_sync() -> LSPClientManager:
    """
    Get the singleton LSPClientManager (SYNC version).

    ONLY call from non-LSP threads (e.g., main thread).
    Calling from the LSP loop thread will DEADLOCK!

    Thread-safe. Creates manager on first call.

    Raises:
        RuntimeError: If manager creation times out or fails
    """
    global _manager

    _ensure_runtime()

    with _lock:
        if _manager is None:
            # Create manager on the LSP loop thread
            future = asyncio.run_coroutine_threadsafe(
                _create_manager_async(),
                _loop
            )
            try:
                _manager = future.result(timeout=30.0)
                logger.info(f"LSP manager created (id={id(_manager)})")
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise RuntimeError(
                    "LSP manager creation timed out after 30s. "
                    "The LSP runtime may be overloaded or stuck."
                )
            except Exception as e:
                logger.error(f"LSP manager creation failed: {e}")
                raise RuntimeError(f"Failed to create LSP manager: {e}") from e

        return _manager


async def get_manager_async() -> LSPClientManager:
    """
    Get the singleton LSPClientManager (ASYNC version).

    Call from code running ON the LSP loop (e.g., inside _execute_async).
    Does not block - creates manager directly if needed.

    Raises:
        RuntimeError: If called from wrong event loop (use get_manager_sync instead)
    """
    global _manager

    # HARD GUARD: Ensure we're on the LSP loop
    _ensure_runtime()

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            "get_manager_async() called outside async context. "
            "Use get_manager_sync() from sync code, or lsp_run() to submit coroutines."
        )

    if _loop is None or current_loop is not _loop:
        raise RuntimeError(
            f"get_manager_async() called from wrong event loop! "
            f"current_loop={id(current_loop)}, lsp_loop={id(_loop) if _loop else None}. "
            f"Use get_manager_sync() from non-LSP threads, or lsp_run() to submit coroutines."
        )

    if _manager is None:
        _manager = LSPClientManager()
        logger.info(f"LSP manager created async (id={id(_manager)})")

    return _manager


async def _create_manager_async() -> LSPClientManager:
    """Create manager on the LSP event loop."""
    return LSPClientManager()


async def _run_locked(coro: Coroutine[Any, Any, T], timeout: float) -> T:
    """
    Run coroutine under the request lock with enforced timeout.

    Serializes LSP requests to avoid concurrency issues with multilspy/server.
    The timeout is enforced INSIDE the loop via asyncio.wait_for(), ensuring
    the coroutine is actually cancelled if it takes too long (not just the caller).

    Args:
        coro: Coroutine to run
        timeout: Maximum execution time in seconds

    Raises:
        asyncio.TimeoutError: If coroutine exceeds timeout
    """
    assert _request_lock is not None, "LSP runtime not initialized"
    async with _request_lock:
        return await asyncio.wait_for(coro, timeout=timeout)


def lsp_run(coro: Coroutine[Any, Any, T], timeout: float = 30.0) -> T:
    """
    Run a coroutine on the LSP event loop and wait for result.

    Serializes requests using internal lock to avoid LSP server concurrency issues.
    Timeout is enforced inside the loop via asyncio.wait_for().

    TIMEOUT BEHAVIOR:
        - On timeout, the coroutine is cancelled cleanly via asyncio.wait_for()
        - NO automatic restart on timeout - that causes instability
        - A clean TimeoutError is raised for the caller to handle
        - The runtime remains healthy for subsequent requests

    Args:
        coro: Coroutine to run
        timeout: Maximum wait time in seconds

    Returns:
        Coroutine result

    Raises:
        TimeoutError: If timeout exceeded (coroutine cancelled cleanly)
        RuntimeError: If called from LSP thread (would deadlock) or runtime unhealthy
        Exception: Any exception from the coroutine
    """
    _ensure_runtime()

    # GUARD: Prevent calling from LSP thread (would deadlock on _request_lock)
    if threading.current_thread() is _thread:
        raise RuntimeError(
            "lsp_run() called from LSP runtime thread - this would deadlock! "
            "Use 'await coro' directly since you're already on the LSP loop."
        )

    # Wrap in lock with enforced timeout inside the loop
    future = asyncio.run_coroutine_threadsafe(_run_locked(coro, timeout), _loop)

    # Grace period: asyncio.wait_for should cancel coro at `timeout`,
    # so we give extra time for cancellation to propagate.
    # This should be generous enough to not trigger on normal timeouts.
    grace_period = 5.0

    try:
        return future.result(timeout=timeout + grace_period)

    except concurrent.futures.TimeoutError:
        # The outer future.result() timed out - this means either:
        # 1. The asyncio.wait_for() inside didn't fire (loop stuck)
        # 2. The cancellation is taking longer than grace_period
        #
        # DO NOT force restart here - it causes instability.
        # Just cancel and return error. The loop may recover on its own.
        future.cancel()

        # Check if runtime is still healthy
        if not _is_runtime_healthy():
            logger.error(
                f"LSP request timed out after {timeout}s + {grace_period}s grace. "
                f"Runtime appears unhealthy (loop closed or thread dead). "
                f"Next request will trigger restart."
            )
        else:
            logger.warning(
                f"LSP request timed out after {timeout}s + {grace_period}s grace. "
                f"Runtime still healthy. Request cancelled."
            )

        raise TimeoutError(
            f"LSP request timed out after {timeout}s. "
            f"The query may be too complex or the server is slow. "
            f"Please retry."
        )

    except asyncio.TimeoutError:
        # This is raised when asyncio.wait_for() inside _run_locked times out
        # The coroutine was properly cancelled - this is a "clean" timeout
        raise TimeoutError(
            f"LSP request timed out after {timeout}s. "
            f"The query may be too complex or the server is slow."
        )

    except asyncio.CancelledError:
        # Request was cancelled (e.g., by user interrupt)
        raise TimeoutError(
            f"LSP request was cancelled."
        )

    except Exception:
        # Re-raise other exceptions as-is
        raise


def shutdown():
    """
    Shutdown the LSP runtime gracefully.

    Closes all LSP servers and stops the event loop.
    Waits for all pending tasks to complete before stopping.
    """
    global _manager, _loop, _thread, _request_lock

    with _lock:
        # Clear ready signal to prevent stale reads on potential restart
        _loop_ready.clear()

        if _loop is None or _thread is None:
            return

        logger.info("Shutting down LSP runtime...")

        # Close servers first
        if _manager is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    _manager.close_all_servers(),
                    _loop
                )
                future.result(timeout=10.0)
            except Exception as e:
                logger.warning(f"Error closing LSP servers: {e}")
            _manager = None

        # Cancel all pending tasks on the loop
        if not _loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    _cancel_all_tasks(),
                    _loop
                )
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error cancelling pending tasks: {e}")

        # Stop the loop
        if not _loop.is_closed():
            try:
                _loop.call_soon_threadsafe(_loop.stop)
            except Exception:
                pass

        # Wait for thread to finish - must complete before clearing globals
        if _thread is not None and _thread.is_alive():
            _thread.join(timeout=10.0)
            if _thread.is_alive():
                logger.warning("LSP runtime thread did not stop within 10s")

        # Only clear globals after thread is stopped
        _loop = None
        _thread = None
        _request_lock = None

        logger.info("LSP runtime shutdown complete")


async def _cancel_all_tasks():
    """Cancel all pending tasks on the current loop (except this one)."""
    loop = asyncio.get_running_loop()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]

    if not tasks:
        return

    logger.info(f"Cancelling {len(tasks)} pending tasks...")

    for task in tasks:
        task.cancel()

    # Wait for all tasks to complete cancellation
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("All pending tasks cancelled")


# Register shutdown on process exit
atexit.register(shutdown)
