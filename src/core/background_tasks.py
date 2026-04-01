"""
Background Task Registry - Manages asyncio.Tasks for background commands.

Allows the LLM to launch long-running commands (tests, builds, lints)
asynchronously, continue working, and get notified when results are ready.

Phase 1: Ephemeral registry (no session persistence). Gated by feature flag.

Design:
- Uses asyncio.create_subprocess_shell (Unix) / asyncio.create_subprocess_exec
  (Windows/PowerShell) -- non-blocking, no thread pool.
- Reuses check_command_safety() and clamp_timeout() from command_safety.py.
- Max 5 concurrent tasks. Default timeout 300s, max 1800s.
- Completion callback fires for status bar updates.
"""

import asyncio
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.observability import get_logger
from src.tools.command_safety import check_command_safety
from src.tools.powershell_sanitize import sanitize_for_powershell

logger = get_logger(__name__)

MAX_CONCURRENT_TASKS = 5
DEFAULT_BG_TIMEOUT = 300  # 5 minutes
MAX_BG_TIMEOUT = 1800  # 30 minutes
MAX_OUTPUT_BYTES = 512_000  # 512 KB capture limit per stream


class BackgroundTaskStatus(str, Enum):
    """Status of a background task."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTaskInfo:
    """Information about a background task."""

    task_id: str
    command: str
    description: str
    status: BackgroundTaskStatus
    working_dir: str | None = None
    timeout: int = DEFAULT_BG_TIMEOUT
    start_time: float = 0.0
    end_time: float = 0.0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def _clamp_bg_timeout(timeout: int | None) -> int:
    """Clamp timeout to background task bounds."""
    if timeout is None:
        return DEFAULT_BG_TIMEOUT
    return max(1, min(int(timeout), MAX_BG_TIMEOUT))


class BackgroundTaskRegistry:
    """Registry managing background asyncio.Tasks for shell commands.

    Thread-safety: All methods are async or called from the asyncio event loop.
    No thread pool needed -- subprocess management is natively async.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTaskInfo] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}
        self._completed_queue: list[BackgroundTaskInfo] = []
        self._counter: int = 0
        self._completion_callback: Callable[[int, BackgroundTaskInfo | None], Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def launch(
        self,
        command: str,
        description: str = "",
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> tuple[str | None, str | None]:
        """Start a background command. Returns immediately.

        Args:
            command: Shell command to execute.
            description: Human-readable description.
            working_dir: Working directory for the command.
            timeout: Timeout in seconds (default 300, max 1800).

        Returns:
            (task_id, None) on success, (None, error_message) on failure.
        """
        # Safety check (same as run_command)
        # Background tasks have no approval UI, so both BLOCK and NEEDS_APPROVAL
        # are treated as hard blocks here.
        from src.tools.command_safety import CommandSafety

        safety_result = check_command_safety(command)
        if safety_result.safety == CommandSafety.BLOCK:
            return None, f"[BLOCKED] {safety_result.reason}"
        if safety_result.safety == CommandSafety.NEEDS_APPROVAL:
            return None, (
                f"[BLOCKED] {safety_result.reason} "
                "(background tasks cannot request user approval)"
            )

        # Capacity check
        active = self._active_count()
        if active >= MAX_CONCURRENT_TASKS:
            return None, (
                f"Maximum concurrent background tasks reached ({MAX_CONCURRENT_TASKS}). "
                "Wait for a running task to complete or cancel one."
            )

        clamped_timeout = _clamp_bg_timeout(timeout)

        # Generate ID
        self._counter += 1
        task_id = f"bg-{self._counter}"

        info = BackgroundTaskInfo(
            task_id=task_id,
            command=command,
            description=description or command[:80],
            status=BackgroundTaskStatus.RUNNING,
            working_dir=working_dir,
            timeout=clamped_timeout,
            start_time=time.monotonic(),
        )
        self._tasks[task_id] = info

        # Launch async task
        async_task = asyncio.create_task(
            self._run_command(task_id, command, working_dir, clamped_timeout)
        )
        self._async_tasks[task_id] = async_task

        logger.info(
            "background_task_launched",
            task_id=task_id,
            command=command[:100],
            timeout=clamped_timeout,
        )

        # Notify callback that a new task started (count changed)
        self._fire_completion_callback(None)

        return task_id, None

    def get_status(self, task_id: str) -> BackgroundTaskInfo | None:
        """Get task info by ID. Returns None if not found."""
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        """Get full result with stdout/stderr. Returns None if still running or not found."""
        info = self._tasks.get(task_id)
        if info is None:
            return None
        if info.status == BackgroundTaskStatus.RUNNING:
            return None

        elapsed = info.end_time - info.start_time if info.end_time else 0
        return {
            "task_id": info.task_id,
            "command": info.command,
            "description": info.description,
            "status": info.status.value,
            "exit_code": info.exit_code,
            "stdout": info.stdout,
            "stderr": info.stderr,
            "error": info.error,
            "elapsed_seconds": round(elapsed, 1),
        }

    async def cancel(self, task_id: str) -> tuple[bool, str]:
        """Cancel a running task.

        Returns:
            (success, message)
        """
        info = self._tasks.get(task_id)
        if info is None:
            return False, f"Task '{task_id}' not found"

        if info.status != BackgroundTaskStatus.RUNNING:
            return False, f"Task '{task_id}' is not running (status: {info.status.value})"

        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()

        info.status = BackgroundTaskStatus.CANCELLED
        info.end_time = time.monotonic()
        self._completed_queue.append(info)
        self._fire_completion_callback(info)

        logger.info("background_task_cancelled", task_id=task_id)
        return True, f"Task '{task_id}' cancelled"

    def drain_completed(self) -> list[BackgroundTaskInfo]:
        """Return and clear newly-completed tasks."""
        completed = list(self._completed_queue)
        self._completed_queue.clear()
        return completed

    def remove_from_completed(self, task_id: str) -> None:
        """Remove a specific task from the completed queue without draining others.

        Use this when a task has already been delivered via another path (e.g.
        the idle _chat_queue path in stdio_server) to prevent the tool loop's
        drain_completed() from re-delivering it.
        """
        self._completed_queue = [t for t in self._completed_queue if t.task_id != task_id]

    async def cancel_all(self) -> int:
        """Cancel all running tasks. Returns count cancelled."""
        count = 0
        for task_id, info in list(self._tasks.items()):
            if info.status == BackgroundTaskStatus.RUNNING:
                async_task = self._async_tasks.get(task_id)
                if async_task and not async_task.done():
                    async_task.cancel()
                info.status = BackgroundTaskStatus.CANCELLED
                info.end_time = time.monotonic()
                count += 1
        if count:
            logger.info("background_tasks_cancel_all", count=count)
        return count

    def set_completion_callback(
        self, fn: Callable[[int, Optional["BackgroundTaskInfo"]], Any]
    ) -> None:
        """Register callback fired on task start/completion.

        Args:
            fn: Callback taking (active_count, completed_task_info_or_none).
                completed_task is None on launch, populated on completion.
        """
        self._completion_callback = fn

    def cleanup(self) -> None:
        """Synchronous cleanup for shutdown path.

        Schedules cancel_all if an event loop is running.
        """
        for _task_id, async_task in list(self._async_tasks.items()):
            if not async_task.done():
                async_task.cancel()
        self._async_tasks.clear()

    def active_count(self) -> int:
        """Return number of currently running tasks."""
        return self._active_count()

    def all_tasks(self) -> list[BackgroundTaskInfo]:
        """Return all tasks (for status display)."""
        return list(self._tasks.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _active_count(self) -> int:
        return sum(
            1 for info in self._tasks.values() if info.status == BackgroundTaskStatus.RUNNING
        )

    def _fire_completion_callback(self, completed_task: BackgroundTaskInfo | None = None) -> None:
        if self._completion_callback:
            try:
                self._completion_callback(self._active_count(), completed_task)
            except Exception as e:
                logger.warning(f"Completion callback error: {e}")

    async def _run_command(
        self,
        task_id: str,
        command: str,
        working_dir: str | None,
        timeout: int,
    ) -> None:
        """Execute command as async subprocess and capture output."""
        info = self._tasks[task_id]
        communicate_task = None

        # Detect preferred shell; only sanitize for PowerShell
        from src.platform import detect_preferred_shell, get_bash_env

        shell_info = detect_preferred_shell()
        if shell_info["syntax"] == "powershell":
            command = sanitize_for_powershell(command)

        try:
            # Platform-specific subprocess creation
            # stdin=DEVNULL is MANDATORY -- see CLAUDE.md "subprocess.run stdin inheritance".
            # Without it, child processes inherit the parent's stdin handle, causing
            # deadlocks in stdio mode where a background thread reads stdin for JSON.
            # CREATE_NO_WINDOW / start_new_session isolate the subprocess from the
            # parent terminal, preventing escape sequences from leaking into the TUI.
            if platform.system() == "Windows":
                import subprocess as _sp

                if shell_info["shell"] == "bash":
                    bash_env = get_bash_env(shell_info["path"])
                    process = await asyncio.create_subprocess_exec(
                        shell_info["path"],
                        "-c",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        stdin=asyncio.subprocess.DEVNULL,
                        cwd=working_dir,
                        creationflags=_sp.CREATE_NO_WINDOW,
                        env=bash_env,
                    )
                else:
                    process = await asyncio.create_subprocess_exec(
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        stdin=asyncio.subprocess.DEVNULL,
                        cwd=working_dir,
                        creationflags=_sp.CREATE_NO_WINDOW,
                    )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    cwd=working_dir,
                    start_new_session=True,
                )

            # Use asyncio.wait instead of asyncio.wait_for: in Python 3.12+,
            # wait_for cancels the inner coroutine and blocks until it responds
            # before raising TimeoutError. On Windows/IOCP, communicate() may
            # not cancel cleanly while pipes are open (grandchild process keeps
            # pipe handles alive), causing wait_for to hang indefinitely.
            communicate_task = asyncio.create_task(process.communicate())
            done, pending = await asyncio.wait({communicate_task}, timeout=timeout)

            if pending:
                # Timeout: kill entire process tree first (closes pipes), then cancel task.
                await self._kill_process(process)
                communicate_task.cancel()
                try:
                    await communicate_task
                except (asyncio.CancelledError, Exception):
                    pass
                info.status = BackgroundTaskStatus.TIMED_OUT
                info.error = f"Command timed out after {timeout}s"
                logger.warning(
                    "background_task_timeout",
                    task_id=task_id,
                    timeout=timeout,
                )
            else:
                stdout_bytes, stderr_bytes = communicate_task.result()
                info.stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
                info.stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
                info.exit_code = process.returncode

                if process.returncode == 0:
                    info.status = BackgroundTaskStatus.COMPLETED
                else:
                    info.status = BackgroundTaskStatus.FAILED

        except asyncio.CancelledError:
            # Task was cancelled via cancel() or cancel_all()
            if communicate_task is not None and not communicate_task.done():
                communicate_task.cancel()
            info.status = BackgroundTaskStatus.CANCELLED
            raise
        except Exception as e:
            info.status = BackgroundTaskStatus.FAILED
            info.error = f"{type(e).__name__}: {e}"
            logger.error(
                "background_task_error",
                task_id=task_id,
                error=str(e),
            )
        finally:
            info.end_time = time.monotonic()
            # Guard: if status is still RUNNING here, something bypassed all except handlers
            # (e.g. BaseException subclass like KeyboardInterrupt). Treat as FAILED so the
            # notification system never sees a RUNNING task as "completed".
            if info.status == BackgroundTaskStatus.RUNNING:
                info.status = BackgroundTaskStatus.FAILED
                info.error = info.error or "Task terminated unexpectedly"
            # Only queue and notify if not already cancelled (cancel() handles its own queueing)
            if info.status != BackgroundTaskStatus.CANCELLED:
                self._completed_queue.append(info)
            self._fire_completion_callback(info)

            logger.info(
                "background_task_finished",
                task_id=task_id,
                status=info.status.value,
                exit_code=info.exit_code,
                elapsed=round(info.end_time - info.start_time, 1),
            )

    async def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        """Kill process and wait for exit. On Windows, kills entire process tree."""
        if platform.system() == "Windows":
            # taskkill /F /T kills PowerShell and all its child processes (e.g. ping).
            # process.kill() alone only kills the direct child, leaving grandchildren
            # running with pipe handles open.
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(kill_proc.wait(), timeout=5.0)
            except Exception:
                pass
        else:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
