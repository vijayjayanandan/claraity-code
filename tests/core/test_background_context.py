"""Tests for background context injection."""

import pytest

from src.core.background_tasks import BackgroundTaskInfo, BackgroundTaskStatus
from src.core.background_context import (
    inject_background_task_completions,
    OUTPUT_PREVIEW_CHARS,
)


def _make_task(
    task_id: str = "bg-1",
    command: str = "echo test",
    description: str = "test task",
    status: BackgroundTaskStatus = BackgroundTaskStatus.COMPLETED,
    exit_code: int = 0,
    stdout: str = "test output",
    stderr: str = "",
    error: str = "",
) -> BackgroundTaskInfo:
    return BackgroundTaskInfo(
        task_id=task_id,
        command=command,
        description=description,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        error=error,
        start_time=100.0,
        end_time=105.0,
    )


class TestInjectBackgroundTaskCompletions:
    def test_noop_on_empty_list(self):
        """No-op when completed_tasks is empty."""
        context = [{"role": "system", "content": "system msg"}]
        inject_background_task_completions(context, [])
        assert len(context) == 1  # No change

    def test_injects_user_role_message(self):
        """Injects a user-role message into context."""
        context = []
        task = _make_task()
        inject_background_task_completions(context, [task])
        assert len(context) == 1
        msg = context[0]
        assert msg["role"] == "user"
        assert "[BACKGROUND TASK UPDATE]" in msg["content"]

    def test_contains_task_id_and_status(self):
        """Injected message contains task ID and status."""
        context = []
        task = _make_task(task_id="bg-42", status=BackgroundTaskStatus.COMPLETED)
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "bg-42" in content
        assert "COMPLETED" in content

    def test_contains_exit_code(self):
        """Injected message contains exit code."""
        context = []
        task = _make_task(exit_code=1, status=BackgroundTaskStatus.FAILED)
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "Exit code: 1" in content

    def test_contains_output_preview(self):
        """Injected message contains stdout preview."""
        context = []
        task = _make_task(stdout="All 42 tests passed!")
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "All 42 tests passed!" in content

    def test_output_preview_truncated(self):
        """Long output is truncated at OUTPUT_PREVIEW_CHARS."""
        context = []
        long_output = "x" * (OUTPUT_PREVIEW_CHARS + 200)
        task = _make_task(stdout=long_output)
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "more chars" in content

    def test_stderr_used_when_no_stdout(self):
        """When stdout is empty, stderr is shown instead."""
        context = []
        task = _make_task(stdout="", stderr="error details here")
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "error details here" in content

    def test_error_field_included(self):
        """Task error field is shown."""
        context = []
        task = _make_task(
            status=BackgroundTaskStatus.TIMED_OUT,
            error="Command timed out after 300s",
        )
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "timed out" in content

    def test_multiple_tasks(self):
        """Multiple completed tasks are all included."""
        context = []
        tasks = [
            _make_task(task_id="bg-1", description="first"),
            _make_task(task_id="bg-2", description="second"),
        ]
        inject_background_task_completions(context, tasks)
        assert len(context) == 1  # Single message
        content = context[0]["content"]
        assert "bg-1" in content
        assert "bg-2" in content
        assert "first" in content
        assert "second" in content

    def test_includes_no_action_needed_hint(self):
        """Message indicates full output is included and no tool call needed."""
        context = []
        task = _make_task()
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "No further action needed" in content

    def test_command_included(self):
        """Injected message includes the command."""
        context = []
        task = _make_task(command="pytest tests/ -v")
        inject_background_task_completions(context, [task])
        content = context[0]["content"]
        assert "pytest tests/ -v" in content
