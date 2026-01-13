"""Planning tool for complex multi-step tasks."""

from typing import Dict, Any, Optional, TYPE_CHECKING
from .base import Tool, ToolResult, ToolStatus

if TYPE_CHECKING:
    from src.workflow import TaskAnalyzer, TaskPlanner


class CreateExecutionPlanTool(Tool):
    """Tool for creating detailed execution plans for complex tasks.

    This tool wraps the workflow system (TaskAnalyzer + TaskPlanner) and makes
    planning available as a tool that the LLM can invoke when it determines a
    task is complex enough to warrant explicit planning.

    Following industry best practice: Let the LLM decide when to plan, rather
    than application code making that decision via routing logic.
    """

    def __init__(
        self,
        task_analyzer: 'TaskAnalyzer',
        task_planner: 'TaskPlanner'
    ):
        """Initialize planning tool.

        Args:
            task_analyzer: Task analyzer for analyzing task characteristics
            task_planner: Task planner for creating execution plans
        """
        super().__init__(
            name="create_execution_plan",
            description=(
                "Create a detailed execution plan for complex multi-step tasks. "
                "Use this when the task requires: (1) Multiple files/steps, "
                "(2) Architectural decisions, (3) High-risk operations, or "
                "(4) Coordination across systems. Returns a structured plan "
                "with steps, dependencies, time estimates, and risk assessment."
            )
        )
        self.task_analyzer = task_analyzer
        self.task_planner = task_planner

    def execute(
        self,
        task_description: str,
        complexity_hint: Optional[str] = None,
        **kwargs: Any
    ) -> ToolResult:
        """Create execution plan for the given task.

        Args:
            task_description: Clear description of the task to plan
            complexity_hint: Optional hint about complexity (simple/moderate/complex/very_complex)
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult containing the formatted execution plan
        """
        try:
            if not task_description or not task_description.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="task_description cannot be empty"
                )

            # Step 1: Analyze the task using TaskAnalyzer (LLM-based)
            analysis = self.task_analyzer.analyze(task_description)

            # Step 2: Create execution plan using TaskPlanner (LLM-based)
            plan = self.task_planner.create_plan(task_description, analysis)

            # Step 3: Format plan for LLM consumption
            formatted_plan = self._format_plan_for_llm(plan, analysis)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=formatted_plan,
                metadata={
                    "task_type": analysis.task_type.value,
                    "complexity": analysis.complexity.value,
                    "risk_level": analysis.risk_level,
                    "requires_approval": analysis.requires_approval,
                    "estimated_files": analysis.estimated_files,
                    "step_count": len(plan.steps),
                    # Store plan object for execution
                    "_plan_object": plan,
                    "_analysis_object": analysis
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to create execution plan: {str(e)}"
            )

    def _format_plan_for_llm(self, plan, analysis) -> str:
        """Format plan in a clear, readable format for LLM.

        Args:
            plan: ExecutionPlan object
            analysis: TaskAnalysis object

        Returns:
            Formatted plan string
        """
        lines = []

        lines.append("="* 60)
        lines.append("EXECUTION PLAN CREATED")
        lines.append("="* 60)
        lines.append("")

        # Task info
        lines.append(f"Task: {plan.task_description}")
        lines.append(f"Type: {analysis.task_type.value}")
        lines.append(f"Complexity: {analysis.complexity.name} ({analysis.complexity.value}/5)")
        lines.append(f"Risk Level: {analysis.risk_level.upper()}")
        lines.append(f"Estimated Time: {plan.total_estimated_time}")
        lines.append(f"Estimated Files: {analysis.estimated_files}")
        lines.append("")

        # Approval requirement
        if analysis.requires_approval:
            lines.append("[WARN] This plan requires user approval before execution")
            lines.append("")

        # Steps
        lines.append("EXECUTION STEPS:")
        lines.append("-" * 60)
        for i, step in enumerate(plan.steps, 1):
            lines.append(f"{i}. {step.description}")
            lines.append(f"   Action: {step.action_type}")
            lines.append(f"   Time: {step.estimated_time}")
            lines.append(f"   Risk: {step.risk}")
            if step.dependencies:
                dep_nums = [d + 1 for d in step.dependencies]
                lines.append(f"   Depends on: Steps {', '.join(map(str, dep_nums))}")
            lines.append("")

        # Success criteria
        if plan.success_criteria:
            lines.append("SUCCESS CRITERIA:")
            lines.append("-" * 60)
            for criterion in plan.success_criteria:
                lines.append(f"- {criterion}")
            lines.append("")

        lines.append("="* 60)
        lines.append("")
        lines.append("To proceed with this plan, execute the steps above using")
        lines.append("the available tools (read_file, edit_file, write_file, etc.)")

        return "\n".join(lines)

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema for LLM."""
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": (
                        "Clear, detailed description of the task to plan. "
                        "Include context about what needs to be done and why."
                    )
                },
                "complexity_hint": {
                    "type": "string",
                    "description": (
                        "Optional hint about task complexity: "
                        "'simple' (1-2 files), "
                        "'moderate' (2-3 files), "
                        "'complex' (4+ files), "
                        "'very_complex' (architecture changes)"
                    ),
                    "enum": ["simple", "moderate", "complex", "very_complex"]
                }
            },
            "required": ["task_description"]
        }


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
