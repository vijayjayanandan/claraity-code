"""Base tool interface and executor."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


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

    def __init__(self):
        """Initialize tool executor."""
        self.tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool to register
        """
        self.tools[tool.name] = tool

    def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool result
        """
        if tool_name not in self.tools:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Tool '{tool_name}' not found"
            )

        tool = self.tools[tool_name]

        try:
            return tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                output=None,
                error=str(e)
            )

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
