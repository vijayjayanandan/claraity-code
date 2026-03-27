"""Tool execution engine for the AI coding agent."""

from .base import Tool, ToolExecutionError, ToolExecutor, ToolNotFoundError, ToolResult
from .checkpoint_tool import CreateCheckpointTool
from .clarify_tool import ClarifyTool
from .delegation import DelegateToSubagentTool
from .file_operations import (
    AppendToFileTool,
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    RunCommandTool,
    WriteFileTool,
)
from .lsp_tools import GetFileOutlineTool, GetSymbolContextTool
from .plan_mode_tools import EnterPlanModeTool, RequestPlanApprovalTool
from .search_tools import GlobTool, GrepTool
from .tool_schemas import (
    ALL_TOOLS,
    CODE_TOOLS,
    EXECUTION_TOOLS,
    FILE_TOOLS,
    PLAN_MODE_TOOLS,
    WEB_TOOLS,
    get_tools_for_task,
)
from .web_tools import (
    RunBudget,
    TavilyProvider,
    UrlSafety,
    WebFetchTool,
    WebSearchProvider,
    WebSearchTool,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolExecutor",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "AppendToFileTool",
    "ListDirectoryTool",
    "RunCommandTool",
    "GrepTool",
    "GlobTool",
    "GetFileOutlineTool",
    "GetSymbolContextTool",
    "DelegateToSubagentTool",
    "CreateCheckpointTool",
    "ClarifyTool",
    # Plan mode tools
    "EnterPlanModeTool",
    "RequestPlanApprovalTool",
    # Web tools
    "WebSearchTool",
    "WebFetchTool",
    "WebSearchProvider",
    "TavilyProvider",
    "UrlSafety",
    "RunBudget",
    # Tool schemas for LLM function calling
    "ALL_TOOLS",
    "FILE_TOOLS",
    "CODE_TOOLS",
    "EXECUTION_TOOLS",
    "WEB_TOOLS",
    "PLAN_MODE_TOOLS",
    "get_tools_for_task",
]
