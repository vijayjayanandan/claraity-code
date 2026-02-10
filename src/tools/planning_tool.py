"""Todo tracking tool for multi-step tasks."""

from typing import Dict, Any, Optional
from .base import Tool, ToolResult, ToolStatus
from .task_state import TaskState


class TodoWriteTool(Tool):
    """Tool for creating and managing task lists."""

    def __init__(self, agent_state: Dict[str, Any] = None):
        """
        Initialize TodoWrite tool.

        Args:
            agent_state: Shared agent state for storing todos
        """
        super().__init__(
            name="todo_write",
            description="Create and update a task list to track progress through multi-step work. Use for complex tasks (3+ steps) to stay organized."
        )
        # Use shared state dict to store todos (will be passed by agent)
        self.agent_state = agent_state if agent_state is not None else {}

    def execute(self, todos: list, **kwargs: Any) -> ToolResult:
        """
        Update the task list.

        Args:
            todos: List of todo items with:
                - content: Task description (imperative form, e.g., "Fix bug")
                - activeForm: Present continuous form (e.g., "Fixing bug")
                - status: "pending" | "in_progress" | "completed"

        Returns:
            ToolResult with updated task list
        """
        try:
            # Validate todos
            for i, todo in enumerate(todos):
                if "content" not in todo:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Todo {i+1} missing 'content' field"
                    )
                if "status" not in todo:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Todo {i+1} missing 'status' field"
                    )
                if "activeForm" not in todo:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Todo {i+1} missing 'activeForm' field"
                    )
                if todo["status"] not in ["pending", "in_progress", "completed"]:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Invalid status: {todo['status']}"
                    )

            # Store todos in agent state
            self.agent_state['todos'] = todos

            # Format summary
            summary_lines = ["Task list updated:"]
            in_progress_count = 0
            completed_count = 0
            pending_count = 0

            for todo in todos:
                status = todo["status"]
                if status == "in_progress":
                    in_progress_count += 1
                    summary_lines.append(f"  [IN PROGRESS] {todo['activeForm']}")
                elif status == "completed":
                    completed_count += 1
                    summary_lines.append(f"  [DONE] {todo['content']}")
                else:  # pending
                    pending_count += 1
                    summary_lines.append(f"  [TODO] {todo['content']}")

            summary = "\n".join(summary_lines)
            summary += f"\n\nProgress: {completed_count} done, {in_progress_count} in progress, {pending_count} pending"

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=summary,
                metadata={
                    "total_tasks": len(todos),
                    "completed": completed_count,
                    "in_progress": in_progress_count,
                    "pending": pending_count,
                    "todos": todos
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update task list: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Array of todo items to track",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description in imperative form"
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Task description in present continuous form"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Current status of the task"
                            }
                        },
                        "required": ["content", "status", "activeForm"]
                    }
                }
            },
            "required": ["todos"]
        }


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
