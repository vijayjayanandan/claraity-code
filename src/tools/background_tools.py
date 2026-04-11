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

    _SCHEMA_NAME = "check_background_task"

    def __init__(self, registry: BackgroundTaskRegistry):
        from src.tools.tool_schemas import _SCHEMA_REGISTRY
        _def = _SCHEMA_REGISTRY["check_background_task"]
        super().__init__(name=_def.name, description=_def.description)
        self._registry = registry

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
                        "elapsed_seconds": round(elapsed, 1),
                    },
                    indent=2,
                ),
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=json.dumps(result, indent=2),
        )
