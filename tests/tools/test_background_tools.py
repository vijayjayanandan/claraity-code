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
