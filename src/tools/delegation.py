"""Subagent delegation tool for LLM tool calling interface."""

from typing import Dict, Any, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from src.subagents import SubAgentManager

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class DelegateToSubagentTool(Tool):
    """Tool for delegating tasks to specialized subagents.

    Enables the LLM to invoke subagents for specialized tasks like code review,
    test writing, or documentation. Subagents operate with independent context
    windows, preventing pollution of the main conversation.

    Benefits:
    - Independent context (no pollution of main agent's conversation)
    - Specialized expertise (custom system prompts for specific domains)
    - Focused execution (subagent only sees relevant task, not full history)

    Example:
        The LLM can invoke this tool:
        <TOOL_CALL>
        tool: delegate_to_subagent
        arguments:
          subagent: code-reviewer
          task: Review src/api.py for security vulnerabilities and code quality
        </TOOL_CALL>
    """

    def __init__(self, subagent_manager: 'SubAgentManager'):
        """Initialize delegation tool.

        Args:
            subagent_manager: SubAgentManager instance from main agent
        """
        self.subagent_manager = subagent_manager

        # Generate dynamic description with available subagents
        description = self._generate_description()

        super().__init__(
            name="delegate_to_subagent",
            description=description
        )

    def _generate_description(self) -> str:
        """Generate dynamic tool description listing available subagents.

        This ensures the LLM always knows which subagents are available and
        what they specialize in.

        Returns:
            Formatted description with available subagents
        """
        available = self.subagent_manager.get_available_subagents()

        if not available:
            return "Delegate task to specialized subagent. (No subagents currently available)"

        # Build description with subagent details
        descriptions = []
        for name in available:
            info = self.subagent_manager.get_subagent_info(name)
            if info:
                descriptions.append(f"  - {name}: {info['description']}")

        subagent_list = "\n".join(descriptions)

        return f"""Delegate a task to a specialized subagent for focused execution.

Available subagents:
{subagent_list}

When to use:
- Task requires specialized expertise (code review, testing, documentation)
- Task can be isolated from main conversation context
- You need independent analysis without context pollution
- Complex task benefits from focused, specialized attention

Benefits:
- Independent context window (won't pollute main conversation)
- Specialized system prompts optimized for specific tasks
- Parallel execution possible (multiple subagents can run concurrently)

Use this tool proactively when appropriate!"""

    def execute(self, subagent: str, task: str, **kwargs: Any) -> ToolResult:
        """Execute subagent delegation.

        Args:
            subagent: Name of the subagent to use (e.g., 'code-reviewer')
            task: Clear description of the task to delegate
            **kwargs: Additional arguments (currently unused, for future extension)

        Returns:
            ToolResult with subagent output or error
        """
        logger.info(f"Tool: Delegating to subagent '{subagent}': {task[:100]}...")

        # Validate inputs
        if not subagent or not subagent.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Subagent name is required and cannot be empty"
            )

        if not task or not task.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Task description is required and cannot be empty"
            )

        # Delegate to subagent
        result = self.subagent_manager.delegate(
            subagent_name=subagent.strip(),
            task_description=task.strip()
        )

        # Check if subagent was found
        if not result:
            available = self.subagent_manager.get_available_subagents()
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Subagent '{subagent}' not found. Available: {', '.join(available)}"
            )

        # Return result based on success
        if result.success:
            logger.info(
                f"Tool: Subagent '{subagent}' completed successfully "
                f"({result.execution_time:.2f}s, {len(result.tool_calls)} tools)"
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=result.output,
                metadata={
                    "subagent": result.subagent_name,
                    "execution_time": result.execution_time,
                    "tools_used": len(result.tool_calls),
                    "tool_calls": [
                        {
                            "tool": tc.get("tool"),
                            "success": tc.get("success")
                        }
                        for tc in result.tool_calls
                    ]
                }
            )
        else:
            logger.error(f"Tool: Subagent '{subagent}' failed: {result.error}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=result.error or f"Subagent '{subagent}' execution failed"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get tool parameters schema.

        Returns:
            JSON schema for tool parameters
        """
        return {
            "type": "object",
            "properties": {
                "subagent": {
                    "type": "string",
                    "description": "Name of the subagent to use (e.g., 'code-reviewer', 'test-writer', 'doc-writer')"
                },
                "task": {
                    "type": "string",
                    "description": "Clear, detailed description of the task to delegate to the subagent"
                }
            },
            "required": ["subagent", "task"]
        }
