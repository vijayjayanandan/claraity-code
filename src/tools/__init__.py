"""Tool execution engine for the AI coding agent."""

from .base import Tool, ToolResult, ToolExecutor, ToolNotFoundError, ToolExecutionError
from .file_operations import (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    AppendToFileTool,
    ListDirectoryTool,
    RunCommandTool,
)
from .code_search import SearchCodeTool, AnalyzeCodeTool
from .search_tools import GrepTool, GlobTool
from .lsp_tools import GetFileOutlineTool, GetSymbolContextTool
from .git_operations import GitStatusTool, GitDiffTool, GitCommitTool
from .delegation import DelegateToSubagentTool
from .task_state import TaskState
from .planning_tool import TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool
from .checkpoint_tool import CreateCheckpointTool
from .clarity_tools import (
    QueryComponentTool,
    QueryDependenciesTool,
    QueryDecisionsTool,
    QueryFlowsTool,
    QueryArchitectureSummaryTool,
    SearchComponentsTool,
    GetNextTaskTool,
    UpdateComponentStatusTool,
    AddArtifactTool,
    GetImplementationSpecTool,
    AddMethodTool,
    AddAcceptanceCriterionTool,
    UpdateMethodTool,
    UpdateAcceptanceCriterionTool,
    UpdateImplementationPatternTool,
)
from .clarity_setup_tool import ClaritySetupTool
from .clarify_tool import ClarifyTool
from .plan_mode_tools import EnterPlanModeTool, RequestPlanApprovalTool
from .web_tools import (
    WebSearchTool,
    WebFetchTool,
    WebSearchProvider,
    TavilyProvider,
    UrlSafety,
    RunBudget,
)
from .tool_schemas import (
    ALL_TOOLS,
    FILE_TOOLS,
    CODE_TOOLS,
    GIT_TOOLS,
    EXECUTION_TOOLS,
    CLARITY_TOOLS,
    TESTING_TOOLS,
    WEB_TOOLS,
    PLAN_MODE_TOOLS,
    get_tools_for_task,
)

# Note: Testing tools (RunTestsTool, DetectTestFrameworkTool) are NOT imported here
# to avoid circular imports. They live in src/testing/ and can be imported directly
# from that module. Tool schemas are registered in tool_schemas.py for LLM usage.

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
    "SearchCodeTool",
    "AnalyzeCodeTool",
    "GrepTool",
    "GlobTool",
    "GetFileOutlineTool",
    "GetSymbolContextTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitCommitTool",
    "DelegateToSubagentTool",
    "TaskState",
    "TaskCreateTool",
    "TaskUpdateTool",
    "TaskListTool",
    "TaskGetTool",
    "CreateCheckpointTool",
    "QueryComponentTool",
    "QueryDependenciesTool",
    "QueryDecisionsTool",
    "QueryFlowsTool",
    "QueryArchitectureSummaryTool",
    "SearchComponentsTool",
    "GetNextTaskTool",
    "UpdateComponentStatusTool",
    "AddArtifactTool",
    "GetImplementationSpecTool",
    "AddMethodTool",
    "AddAcceptanceCriterionTool",
    "UpdateMethodTool",
    "UpdateAcceptanceCriterionTool",
    "UpdateImplementationPatternTool",
    "ClaritySetupTool",
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
    "GIT_TOOLS",
    "EXECUTION_TOOLS",
    "CLARITY_TOOLS",
    "TESTING_TOOLS",
    "WEB_TOOLS",
    "PLAN_MODE_TOOLS",
    "get_tools_for_task",
]
