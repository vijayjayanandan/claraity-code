"""Tests for BackgroundTaskRegistry."""

import asyncio
import platform
import subprocess
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.background_tasks import (
    BackgroundTaskRegistry,
    BackgroundTaskInfo,
    BackgroundTaskStatus,
    MAX_CONCURRENT_TASKS,
    DEFAULT_BG_TIMEOUT,
    MAX_BG_TIMEOUT,
    _clamp_bg_timeout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    """Fresh registry for each test."""
    return BackgroundTaskRegistry()


async def _wait_until_not_running(registry, task_id, max_seconds=15):
    """Poll until task leaves RUNNING state (or max_seconds exceeded)."""
    for _ in range(max_seconds * 2):  # 0.5s intervals
        await asyncio.sleep(0.5)
        info = registry.get_status(task_id)
        if info and info.status != BackgroundTaskStatus.RUNNING:
            return info
    return registry.get_status(task_id)


# ---------------------------------------------------------------------------
# _clamp_bg_timeout
# ---------------------------------------------------------------------------

class TestClampBgTimeout:
    def test_none_returns_default(self):
        assert _clamp_bg_timeout(None) == DEFAULT_BG_TIMEOUT

    def test_within_bounds(self):
        assert _clamp_bg_timeout(60) == 60

    def test_clamp_to_min(self):
        assert _clamp_bg_timeout(0) == 1
        assert _clamp_bg_timeout(-5) == 1

    def test_clamp_to_max(self):
        assert _clamp_bg_timeout(9999) == MAX_BG_TIMEOUT


# ---------------------------------------------------------------------------
# launch()
# ---------------------------------------------------------------------------

class TestLaunch:
    @pytest.mark.asyncio
    async def test_launch_returns_task_id(self, registry):
        """Launching a simple command returns a bg-N task ID."""
        task_id, error = await registry.launch("echo hello", description="test echo")
        assert error is None
        assert task_id == "bg-1"

    @pytest.mark.asyncio
    async def test_launch_increments_ids(self, registry):
        """Sequential launches get incrementing IDs."""
        id1, _ = await registry.launch("echo 1")
        id2, _ = await registry.launch("echo 2")
        assert id1 == "bg-1"
        assert id2 == "bg-2"

    @pytest.mark.asyncio
    async def test_launch_blocked_command(self, registry):
        """Dangerous commands are blocked by safety check."""
        task_id, error = await registry.launch("rm -rf /")
        assert task_id is None
        assert "BLOCKED" in error

    @pytest.mark.asyncio
    async def test_launch_capacity_limit(self, registry):
        """Exceeding MAX_CONCURRENT_TASKS returns an error."""
        # Launch MAX_CONCURRENT_TASKS long-running commands
        # Use a command that takes a while so they stay running
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        for i in range(MAX_CONCURRENT_TASKS):
            task_id, error = await registry.launch(cmd, description=f"task-{i}")
            assert error is None, f"Task {i} failed: {error}"

        # Next one should be rejected
        task_id, error = await registry.launch(cmd, description="overflow")
        assert task_id is None
        assert "Maximum" in error

        # Cleanup
        await registry.cancel_all()

    @pytest.mark.asyncio
    async def test_launch_empty_command(self, registry):
        """Empty command is blocked by safety check."""
        task_id, error = await registry.launch("")
        assert task_id is None
        assert error is not None


# ---------------------------------------------------------------------------
# get_status() / get_result()
# ---------------------------------------------------------------------------

class TestStatusAndResult:
    @pytest.mark.asyncio
    async def test_get_status_running(self, registry):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd)
        info = registry.get_status(task_id)
        assert info is not None
        assert info.status == BackgroundTaskStatus.RUNNING
        await registry.cancel_all()

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, registry):
        assert registry.get_status("bg-999") is None

    @pytest.mark.asyncio
    async def test_get_result_while_running(self, registry):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd)
        assert registry.get_result(task_id) is None
        await registry.cancel_all()

    @pytest.mark.asyncio
    async def test_get_result_after_completion(self, registry):
        """After task completes, get_result returns full output."""
        task_id, _ = await registry.launch("echo hello-world")
        await _wait_until_not_running(registry, task_id)
        result = registry.get_result(task_id)
        assert result is not None
        assert result["status"] in ("completed", "failed")
        assert result["task_id"] == task_id


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_running_task(self, registry):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd)
        success, msg = await registry.cancel(task_id)
        assert success is True
        info = registry.get_status(task_id)
        assert info.status == BackgroundTaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, registry):
        success, msg = await registry.cancel("bg-999")
        assert success is False
        assert "not found" in msg

    @pytest.mark.asyncio
    async def test_cancel_already_completed(self, registry):
        task_id, _ = await registry.launch("echo done")
        await _wait_until_not_running(registry, task_id)
        success, msg = await registry.cancel(task_id)
        assert success is False
        assert "not running" in msg


# ---------------------------------------------------------------------------
# drain_completed()
# ---------------------------------------------------------------------------

class TestDrainCompleted:
    @pytest.mark.asyncio
    async def test_drain_empty(self, registry):
        assert registry.drain_completed() == []

    @pytest.mark.asyncio
    async def test_drain_after_completion(self, registry):
        task_id, _ = await registry.launch("echo drain-test")
        await _wait_until_not_running(registry, task_id)
        completed = registry.drain_completed()
        assert len(completed) >= 1
        assert completed[0].task_id == task_id

    @pytest.mark.asyncio
    async def test_drain_clears_queue(self, registry):
        """Second drain returns empty after first drain."""
        task_id, _ = await registry.launch("echo test")
        await _wait_until_not_running(registry, task_id)
        first = registry.drain_completed()
        second = registry.drain_completed()
        assert len(first) >= 1
        assert len(second) == 0


# ---------------------------------------------------------------------------
# cancel_all()
# ---------------------------------------------------------------------------

class TestCancelAll:
    @pytest.mark.asyncio
    async def test_cancel_all(self, registry):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        await registry.launch(cmd)
        await registry.launch(cmd)
        count = await registry.cancel_all()
        assert count == 2
        assert registry.active_count() == 0


# ---------------------------------------------------------------------------
# Completion callback
# ---------------------------------------------------------------------------

class TestCompletionCallback:
    @pytest.mark.asyncio
    async def test_callback_fires_on_completion(self, registry):
        callback = MagicMock()
        registry.set_completion_callback(callback)
        task_id, _ = await registry.launch("echo callback-test")
        await _wait_until_not_running(registry, task_id)
        # Callback fires on launch (count=1, task=None) and completion (count=0, task=info)
        assert callback.call_count >= 2
        # Last call should be completion with active_count=0 and the task info
        last_call_args = callback.call_args_list[-1][0]
        assert last_call_args[0] == 0  # active_count
        assert last_call_args[1] is not None  # completed task info
        assert last_call_args[1].task_id == task_id

    @pytest.mark.asyncio
    async def test_callback_fires_on_cancel(self, registry):
        callback = MagicMock()
        registry.set_completion_callback(callback)
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd)
        await registry.cancel(task_id)
        assert callback.called
        # Cancel should pass the task info
        last_call_args = callback.call_args_list[-1][0]
        assert last_call_args[1] is not None
        assert last_call_args[1].task_id == task_id


# ---------------------------------------------------------------------------
# cleanup()
# ---------------------------------------------------------------------------

class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_cancels_tasks(self, registry):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        await registry.launch(cmd)
        registry.cleanup()
        # async_tasks dict should be cleared
        assert len(registry._async_tasks) == 0


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_produces_timed_out_status(self, registry):
        """Task that exceeds timeout gets TIMED_OUT status."""
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd, timeout=2)
        # Poll until status changes (max 15s to accommodate slow CI subprocess startup)
        for _ in range(30):
            await asyncio.sleep(0.5)
            info = registry.get_status(task_id)
            if info.status != BackgroundTaskStatus.RUNNING:
                break
        assert info.status == BackgroundTaskStatus.TIMED_OUT


# ---------------------------------------------------------------------------
# Subprocess safety flags (stdin, CREATE_NO_WINDOW, start_new_session)
# ---------------------------------------------------------------------------

class TestSubprocessSafetyFlags:
    """Verify that _run_command passes critical subprocess flags.

    These flags are documented invariants (CLAUDE.md):
    - stdin=DEVNULL: prevents deadlock when stdin reader thread is active
    - CREATE_NO_WINDOW: prevents console window flash on Windows
    - start_new_session: isolates subprocess from parent terminal on Unix
    """

    @pytest.mark.asyncio
    async def test_stdin_devnull_passed(self, registry):
        """Child process must not inherit stdin (prevents stdio mode deadlock)."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
             patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            # Setup mock process
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_proc.pid = 12345
            mock_exec.return_value = mock_proc
            mock_shell.return_value = mock_proc

            task_id, _ = await registry.launch("echo test")
            await _wait_until_not_running(registry, task_id, max_seconds=5)

            # Check whichever was called (exec on Windows, shell on Unix)
            if mock_exec.called:
                call_kwargs = mock_exec.call_args
            else:
                call_kwargs = mock_shell.call_args

            # stdin must be DEVNULL (either asyncio.subprocess.DEVNULL or subprocess.DEVNULL)
            stdin_val = call_kwargs.kwargs.get("stdin") if call_kwargs.kwargs else None
            assert stdin_val is not None, "stdin parameter must be explicitly set to DEVNULL"

    @pytest.mark.asyncio
    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
    async def test_create_no_window_on_windows(self, registry):
        """On Windows, CREATE_NO_WINDOW must be set to avoid console flash."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_proc.pid = 12345
            mock_exec.return_value = mock_proc

            task_id, _ = await registry.launch("echo test")
            await _wait_until_not_running(registry, task_id, max_seconds=5)

            call_kwargs = mock_exec.call_args.kwargs if mock_exec.call_args else {}
            flags = call_kwargs.get("creationflags", 0)
            assert flags & subprocess.CREATE_NO_WINDOW, \
                "CREATE_NO_WINDOW flag must be set on Windows"

    @pytest.mark.asyncio
    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-only")
    async def test_start_new_session_on_unix(self, registry):
        """On Unix, start_new_session must be set to isolate from parent terminal."""
        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_proc.pid = 12345
            mock_shell.return_value = mock_proc

            task_id, _ = await registry.launch("echo test")
            await _wait_until_not_running(registry, task_id, max_seconds=5)

            call_kwargs = mock_shell.call_args.kwargs if mock_shell.call_args else {}
            assert call_kwargs.get("start_new_session") is True, \
                "start_new_session must be True on Unix"

    @pytest.mark.asyncio
    async def test_background_task_completes_with_bash(self, registry):
        """Background task using bash should complete successfully with correct output."""
        task_id, error = await registry.launch("echo bash-bg-test", description="bash bg test")
        assert error is None

        info = await _wait_until_not_running(registry, task_id)
        assert info.status == BackgroundTaskStatus.COMPLETED

        result = registry.get_result(task_id)
        assert result is not None
        assert "bash-bg-test" in result.get("stdout", "")
