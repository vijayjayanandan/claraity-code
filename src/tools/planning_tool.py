"""Todo tracking tool for multi-step tasks."""

from typing import Dict, Any
from .base import Tool, ToolResult, ToolStatus


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
