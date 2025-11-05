"""Base tool interface and executor."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from enum import Enum
import time

if TYPE_CHECKING:
    from src.hooks import HookManager, HookDecision, HookBlockedError


class ToolStatus(str, Enum):
    """Tool execution status."""

    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


class ToolResult(BaseModel):
    """Result from tool execution."""

    tool_name: str
    status: ToolStatus
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ToolStatus.SUCCESS


class Tool(ABC):
    """Abstract base class for tools."""

    def __init__(self, name: str, description: str):
        """
        Initialize tool.

        Args:
            name: Tool name
            description: Tool description
        """
        self.name = name
        self.description = description

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool result
        """
        pass

    def get_schema(self) -> Dict[str, Any]:
        """
        Get tool schema for LLM.

        Returns:
            Tool schema dict
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._get_parameters()
        }

    @abstractmethod
    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        pass


class ToolExecutor:
    """Executor for managing and running tools."""

    def __init__(self, hook_manager: Optional['HookManager'] = None):
        """
        Initialize tool executor.

        Args:
            hook_manager: Optional hook manager for event hooks
        """
        self.tools: Dict[str, Tool] = {}
        self.hook_manager = hook_manager

    def register_tool(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool to register
        """
        self.tools[tool.name] = tool

    def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """
        Execute a tool by name with optional hook integration.

        Performance:
        - Without hooks: 1-10ms (baseline)
        - With hooks: 2-11ms (<1ms hook overhead)

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool result
        """
        # PRE-TOOL-USE HOOK
        if self.hook_manager:
            try:
                from src.hooks import HookDecision, HookBlockedError

                decision, modified_kwargs = self.hook_manager.emit_pre_tool_use(
                    tool=tool_name,
                    arguments=kwargs
                )

                if decision == HookDecision.DENY:
                    return ToolResult(
                        tool_name=tool_name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="Operation denied by hook"
                    )

                # Use modified arguments if hook modified them
                kwargs = modified_kwargs

            except Exception as e:
                # Check if it's a HookBlockedError
                if e.__class__.__name__ == 'HookBlockedError':
                    return ToolResult(
                        tool_name=tool_name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Operation blocked by hook: {str(e)}"
                    )
                # Other errors, log and continue
                import logging
                logging.getLogger(__name__).warning(f"PreToolUse hook error: {e}")

        # Check if tool exists
        if tool_name not in self.tools:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Tool '{tool_name}' not found"
            )

        tool = self.tools[tool_name]
        start_time = time.time()

        # EXECUTE TOOL
        try:
            result = tool.execute(**kwargs)
            success = result.is_success()
            error = result.error
        except Exception as e:
            result = ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e)
            )
            success = False
            error = str(e)

        duration = time.time() - start_time

        # POST-TOOL-USE HOOK
        if self.hook_manager:
            try:
                modified_result = self.hook_manager.emit_post_tool_use(
                    tool=tool_name,
                    arguments=kwargs,
                    result=result.output,
                    success=success,
                    duration=duration,
                    error=error
                )

                # If hook modified the result, use it
                if modified_result is not None:
                    result.output = modified_result

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"PostToolUse hook error: {e}")

        return result

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get list of available tools with schemas.

        Returns:
            List of tool schemas
        """
        return [tool.get_schema() for tool in self.tools.values()]

    def get_tools_description(self) -> str:
        """
        Get formatted description of all tools.

        Returns:
            Formatted tool descriptions
        """
        descriptions = []
        for tool in self.tools.values():
            descriptions.append(f"- {tool.name}: {tool.description}")

        return "\n".join(descriptions)
