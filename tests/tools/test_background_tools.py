"""Tests for background task tools (RunCommandTool background path + CheckBackgroundTaskTool)."""

import asyncio
import json
import platform
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.background_tasks import BackgroundTaskRegistry
from src.tools.background_tools import CheckBackgroundTaskTool
from src.tools.file_operations import RunCommandTool
from src.tools.base import ToolStatus


@pytest.fixture
def registry():
    return BackgroundTaskRegistry()


@pytest.fixture
def run_tool(registry):
    return RunCommandTool(registry=registry)


@pytest.fixture
def run_tool_no_registry():
    return RunCommandTool()


@pytest.fixture
def check_tool(registry):
    return CheckBackgroundTaskTool(registry)


# ---------------------------------------------------------------------------
# RunCommandTool — background=True path
# ---------------------------------------------------------------------------

class TestRunCommandToolBackground:
    @pytest.mark.asyncio
    async def test_background_launch_success(self, run_tool):
        result = await run_tool.execute_async(command="echo hello", background=True)
        assert result.status == ToolStatus.SUCCESS
        assert "bg-1" in result.output
        assert "Background task launched" in result.output

    @pytest.mark.asyncio
    async def test_background_launch_empty_command(self, run_tool):
        result = await run_tool.execute_async(command="", background=True)
        assert result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_background_launch_blocked_command(self, run_tool):
        result = await run_tool.execute_async(command="rm -rf /", background=True)
        assert result.status == ToolStatus.ERROR
        assert "BLOCKED" in result.error

    @pytest.mark.asyncio
    async def test_background_launch_with_description(self, run_tool):
        result = await run_tool.execute_async(
            command="echo test",
            description="Run echo test",
            background=True,
        )
        assert result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_background_no_registry_returns_error(self, run_tool_no_registry):
        result = await run_tool_no_registry.execute_async(
            command="echo test", background=True
        )
        assert result.status == ToolStatus.ERROR
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_background_invalid_working_dir(self, run_tool):
        result = await run_tool.execute_async(
            command="echo test",
            working_directory="/nonexistent/path/xyz",
            background=True,
        )
        assert result.status == ToolStatus.ERROR
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_background_false_delegates_to_sync(self, run_tool):
        """background=False should use the normal sync execute() path."""
        result = await run_tool.execute_async(command="echo foreground", background=False)
        assert result.status == ToolStatus.SUCCESS
        assert "foreground" in result.output

    def test_schema_includes_background_param(self, run_tool):
        schema = run_tool.get_schema()
        assert schema["name"] == "run_command"
        assert "background" in schema["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_capacity_limit(self, run_tool):
        """6th background task should fail with capacity error."""
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        for i in range(5):
            result = await run_tool.execute_async(command=cmd, background=True)
            assert result.status == ToolStatus.SUCCESS, f"Task {i+1} should succeed"
        # 6th should fail
        result = await run_tool.execute_async(command=cmd, background=True)
        assert result.status == ToolStatus.ERROR
        # Clean up
        await run_tool._registry.cancel_all()


# ---------------------------------------------------------------------------
# RunCommandTool — foreground (background=False) unchanged behavior
# ---------------------------------------------------------------------------

class TestRunCommandToolForeground:
    def test_foreground_execute_works(self, run_tool):
        """Normal sync execute still works."""
        result = run_tool.execute(command="echo sync-test")
        assert result.status == ToolStatus.SUCCESS
        assert "sync-test" in result.output

    def test_foreground_empty_command(self, run_tool):
        result = run_tool.execute(command="")
        assert result.status == ToolStatus.ERROR


# ---------------------------------------------------------------------------
# CheckBackgroundTaskTool
# ---------------------------------------------------------------------------

class TestCheckBackgroundTaskTool:
    @pytest.mark.asyncio
    async def test_check_not_found(self, check_tool):
        result = check_tool.execute(task_id="bg-999")
        assert result.status == ToolStatus.ERROR
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_check_running_task(self, registry, check_tool):
        cmd = "ping -n 30 127.0.0.1" if platform.system() == "Windows" else "sleep 30"
        task_id, _ = await registry.launch(cmd)
        result = check_tool.execute(task_id=task_id)
        assert result.status == ToolStatus.SUCCESS
        data = json.loads(result.output)
        assert data["status"] == "running"
        assert data["task_id"] == task_id
        await registry.cancel_all()

    @pytest.mark.asyncio
    async def test_check_completed_task(self, registry, check_tool):
        task_id, _ = await registry.launch("echo check-test")
        await asyncio.sleep(2)
        result = check_tool.execute(task_id=task_id)
        assert result.status == ToolStatus.SUCCESS
        data = json.loads(result.output)
        assert data["status"] in ("completed", "failed")
        assert "exit_code" in data

    def test_get_schema(self, check_tool):
        schema = check_tool.get_schema()
        assert schema["name"] == "check_background_task"
        assert "task_id" in schema["parameters"]["properties"]


# ---------------------------------------------------------------------------
# RunCommandTool — async foreground path (interruptible)
# ---------------------------------------------------------------------------

class FakeProtocol:
    """Minimal UIProtocol stub for interrupt testing."""

    def __init__(self, interrupt_after: int = 0):
        self._calls = 0
        self._interrupt_after = interrupt_after

    def check_interrupted(self) -> bool:
        self._calls += 1
        return self._calls > self._interrupt_after


class TestRunCommandToolForegroundAsync:
    @pytest.mark.asyncio
    async def test_foreground_async_success(self):
        """Async foreground path returns success for a quick command."""
        tool = RunCommandTool()
        result = await tool.execute_async(command="echo async-ok", background=False)
        assert result.status == ToolStatus.SUCCESS
        assert "async-ok" in result.output

    @pytest.mark.asyncio
    async def test_foreground_async_failure(self):
        """Async foreground path returns error for non-zero exit code."""
        tool = RunCommandTool()
        result = await tool.execute_async(command="exit 1", background=False)
        assert result.status == ToolStatus.ERROR
        assert "exit code 1" in result.error

    @pytest.mark.asyncio
    async def test_foreground_async_stderr_captured(self):
        """stderr is captured and included in output."""
        tool = RunCommandTool()
        result = await tool.execute_async(command="echo err >&2", background=False)
        assert "err" in result.output

    @pytest.mark.asyncio
    async def test_foreground_async_empty_command(self):
        """Empty command returns error without launching subprocess."""
        tool = RunCommandTool()
        result = await tool.execute_async(command="", background=False)
        assert result.status == ToolStatus.ERROR
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_foreground_async_blocked_command(self):
        """Safety-blocked command returns error without launching subprocess."""
        tool = RunCommandTool()
        # dd if=/dev/zero is a hard BLOCK (not NEEDS_APPROVAL) in command_safety.py
        result = await tool.execute_async(command="dd if=/dev/zero of=/dev/sda", background=False)
        assert result.status == ToolStatus.ERROR
        assert "BLOCKED" in result.error

    @pytest.mark.asyncio
    async def test_set_ui_protocol_wires_correctly(self):
        """set_ui_protocol() stores the protocol instance."""
        tool = RunCommandTool()
        assert tool._ui_protocol is None
        proto = FakeProtocol()
        tool.set_ui_protocol(proto)
        assert tool._ui_protocol is proto

    @pytest.mark.asyncio
    async def test_interrupt_kills_subprocess_and_returns_partial_output(self):
        """When interrupted, subprocess is killed and partial output returned."""
        tool = RunCommandTool()
        # Protocol returns interrupted=True after first poll
        proto = FakeProtocol(interrupt_after=1)
        tool.set_ui_protocol(proto)

        long_cmd = (
            "ping -n 60 127.0.0.1" if platform.system() == "Windows"
            else "for i in $(seq 1 60); do echo line$i; sleep 0.5; done"
        )
        result = await tool.execute_async(command=long_cmd, background=False)

        assert result.status == ToolStatus.ERROR
        assert "interrupt" in result.error.lower() or "cancel" in result.error.lower()
        assert result.metadata.get("interrupted") is True

    @pytest.mark.asyncio
    async def test_no_protocol_completes_normally(self):
        """Without a UIProtocol wired, foreground commands complete normally."""
        tool = RunCommandTool()
        assert tool._ui_protocol is None
        result = await tool.execute_async(command="echo no-protocol", background=False)
        assert result.status == ToolStatus.SUCCESS
        assert "no-protocol" in result.output

    @pytest.mark.asyncio
    async def test_foreground_async_timeout_returns_partial_output(self):
        """Timeout kills subprocess and returns partial output with timeout error."""
        tool = RunCommandTool()
        long_cmd = (
            "ping -n 60 127.0.0.1" if platform.system() == "Windows"
            else "for i in $(seq 1 60); do echo line$i; sleep 0.1; done"
        )
        # timeout=1 should expire well before the command finishes
        result = await tool.execute_async(command=long_cmd, background=False, timeout=1)
        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.error.lower()
        assert result.metadata.get("timeout") == 1

    @pytest.mark.asyncio
    async def test_foreground_async_working_directory(self, tmp_path):
        """working_directory is passed to subprocess correctly."""
        tool = RunCommandTool()
        result = await tool.execute_async(
            command="pwd" if platform.system() != "Windows" else "cd",
            background=False,
            working_directory=str(tmp_path),
        )
        assert result.status == ToolStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_foreground_async_invalid_working_directory(self):
        """Non-existent working_directory returns error without launching."""
        tool = RunCommandTool()
        result = await tool.execute_async(
            command="echo hi",
            background=False,
            working_directory="/nonexistent/path/xyz",
        )
        assert result.status == ToolStatus.ERROR
        assert "does not exist" in result.error


