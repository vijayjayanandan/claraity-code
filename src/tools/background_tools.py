"""
Background Task Tools - LLM-callable tools for background task management.

Only CheckBackgroundTaskTool lives here. Background *launching* is handled by
RunCommandTool(background=True) in file_operations.py.
"""

import json
from typing import Any, Optional

from src.core.background_tasks import BackgroundTaskRegistry
from src.tools.base import Tool, ToolResult, ToolStatus


class CheckBackgroundTaskTool(Tool):
    """Check status and output of a background task."""

    def __init__(self, registry: BackgroundTaskRegistry):
        super().__init__(
            name="check_background_task",
            description=(
                "Check status or get full output of a background task. "
                "Returns status, exit code, stdout, and stderr. "
                "You will be automatically notified when background tasks complete, "
                "then use this tool to retrieve the full output."
            ),
        )
        self._registry = registry

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Background task ID (e.g., 'bg-1')",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        info = self._registry.get_status(task_id)
        if info is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Background task '{task_id}' not found",
            )

        result = self._registry.get_result(task_id)
        if result is None:
            # Still running -- return a strong instruction to prevent polling loops.
            # The agent will receive a [BACKGROUND TASK UPDATE] notification
            # automatically when the task completes (via drain_completed in the
            # tool loop, or via the stdio/TUI completion callback).
            import time

            elapsed = time.monotonic() - info.start_time
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=json.dumps(
                    {
                        "task_id": info.task_id,
                        "status": "running",
                        "command": info.command,
                        "description": info.description,
                        "elapsed_seconds": round(elapsed, 1),
                        "instruction": (
                            "Task is still running. "
                            "DO NOT call check_background_task again. "
                            "You will receive an automatic [BACKGROUND TASK UPDATE] "
                            "notification when this task completes. "
                            "Continue with other work or end your response."
                        ),
                    },
                    indent=2,
                ),
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=json.dumps(result, indent=2),
        )
