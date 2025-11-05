"""Tool execution engine for the AI coding agent."""

from .base import Tool, ToolResult, ToolExecutor
from .file_operations import (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirectoryTool,
    RunCommandTool,
)
from .code_search import SearchCodeTool, AnalyzeCodeTool
from .git_operations import GitStatusTool, GitDiffTool, GitCommitTool
from .delegation import DelegateToSubagentTool
from .tool_schemas import (
    ALL_TOOLS,
    FILE_TOOLS,
    CODE_TOOLS,
    GIT_TOOLS,
    EXECUTION_TOOLS,
    get_tools_for_task,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolExecutor",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "ListDirectoryTool",
    "RunCommandTool",
    "SearchCodeTool",
    "AnalyzeCodeTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitCommitTool",
    "DelegateToSubagentTool",
    # Tool schemas for LLM function calling
    "ALL_TOOLS",
    "FILE_TOOLS",
    "CODE_TOOLS",
    "GIT_TOOLS",
    "EXECUTION_TOOLS",
    "get_tools_for_task",
]
