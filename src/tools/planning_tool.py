"""CRUD task tracking tools backed by TaskState with file persistence."""

from typing import Dict, Any, Optional
from .base import Tool, ToolResult, ToolStatus
from .task_state import TaskState


# ---------------------------------------------------------------------------
# CRUD Task Tools (backed by TaskState)
# ---------------------------------------------------------------------------

class TaskCreateTool(Tool):
    """Create a new task in the task list."""

    def __init__(self, task_state: TaskState):
        super().__init__(
            name="task_create",
            description="Create a new task to track work. Returns the created task with its ID."
        )
        self.task_state = task_state

    def execute(self, subject: str, description: str = "",
                activeForm: str = "", **kwargs: Any) -> ToolResult:
        try:
            task = self.task_state.create(
                subject=subject,
                description=description,
                active_form=activeForm,
                metadata=kwargs.get("metadata"),
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Created task {task['id']}: {subject}",
                metadata={"task": task},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brief task title (imperative form)"},
                "description": {"type": "string", "description": "Detailed description"},
                "activeForm": {"type": "string", "description": "Present continuous form for spinner"},
            },
            "required": ["subject"],
        }


class TaskUpdateTool(Tool):
    """Update an existing task."""

    def __init__(self, task_state: TaskState):
        super().__init__(
            name="task_update",
            description="Update a task's status, subject, description, or dependencies."
        )
        self.task_state = task_state

    def execute(self, taskId: str, **kwargs: Any) -> ToolResult:
        try:
            result = self.task_state.update(taskId, **kwargs)
            if result is None:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Task {taskId} not found",
                )
            status_text = result.get("status", "updated")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Task {taskId} -> {status_text}",
                metadata={"task": result},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e),
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "taskId": {"type": "string", "description": "ID of the task to update"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                    "description": "New status",
                },
                "subject": {"type": "string", "description": "New subject"},
                "description": {"type": "string", "description": "New description"},
                "activeForm": {"type": "string", "description": "New active form text"},
                "owner": {"type": "string", "description": "Agent or user who owns this task"},
                "metadata": {
                    "type": "object",
                    "description": "Arbitrary key-value metadata to merge into the task. Set a key to null to delete it.",
                    "additionalProperties": True,
                },
                "addBlocks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task IDs that cannot start until this task completes",
                },
                "addBlockedBy": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task IDs that must complete before this task can start",
                },
            },
            "required": ["taskId"],
        }


class TaskListTool(Tool):
    """List all tasks."""

    def __init__(self, task_state: TaskState):
        super().__init__(
            name="task_list",
            description="List all tasks with their status and dependencies."
        )
        self.task_state = task_state

    def execute(self, **kwargs: Any) -> ToolResult:
        tasks = self.task_state.list_all()
        if not tasks:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="No tasks.",
                metadata={"tasks": []},
            )
        lines = []
        for t in tasks:
            sid = t.get("id", "?")
            status = t.get("status", "pending")
            subject = t.get("subject", "")
            lines.append(f"  [{status.upper()}] #{sid}: {subject}")
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output="\n".join(lines),
            metadata={"tasks": tasks},
        )

    def _get_parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}


class TaskGetTool(Tool):
    """Get a single task by ID."""

    def __init__(self, task_state: TaskState):
        super().__init__(
            name="task_get",
            description="Get full details of a task by its ID."
        )
        self.task_state = task_state

    def execute(self, taskId: str, **kwargs: Any) -> ToolResult:
        task = self.task_state.get(taskId)
        if task is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Task {taskId} not found",
            )
        lines = [
            f"Task #{task['id']}: {task.get('subject', '')}",
            f"  Status: {task.get('status', 'pending')}",
        ]
        desc = task.get("description", "")
        if desc:
            lines.append(f"  Description: {desc}")
        blocked_by = task.get("blockedBy", [])
        if blocked_by:
            lines.append(f"  Blocked by: {', '.join(blocked_by)}")
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output="\n".join(lines),
            metadata={"task": task},
        )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "taskId": {"type": "string", "description": "The task ID to retrieve"},
            },
            "required": ["taskId"],
        }
