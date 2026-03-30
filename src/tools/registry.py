"""Stateless tool registry.

Single source of truth for all tools that can run in both the main agent
(in-process) and subprocess subagents. Add new stateless tools here.

Stateful tools (plan mode, director, delegation) that require runtime state
from the main agent are NOT listed here — they are registered manually
in agent.py only.
"""


def get_stateless_tools() -> list:
    """Return instances of all stateless tools.

    Lazy import to avoid circular dependencies at module load time.
    Each tool opens/closes its own resources per execute() call.
    """
    from src.tools.knowledge_tools import (
        BeadBlockTool,
        BeadCreateTool,
        BeadReadyTool,
        BeadUpdateTool,
        KnowledgeAutoLayoutTool,
        KnowledgeExportTool,
        KnowledgeQueryTool,
        KnowledgeScanFilesTool,
        KnowledgeSetMetadataTool,
        KnowledgeUpdateTool,
    )
    from src.tools.clarify_tool import ClarifyTool
    from src.tools.file_operations import (
        AppendToFileTool,
        EditFileTool,
        ListDirectoryTool,
        ReadFileTool,
        RunCommandTool,
        WriteFileTool,
    )
    from src.tools.lsp_tools import GetFileOutlineTool, GetSymbolContextTool
    from src.tools.search_tools import GlobTool, GrepTool
    from src.tools.web_tools import WebFetchTool, WebSearchTool

    return [
        # File operations
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        AppendToFileTool(),
        ListDirectoryTool(),
        RunCommandTool(),
        # Search
        GrepTool(),
        GlobTool(),
        # LSP
        GetFileOutlineTool(),
        GetSymbolContextTool(),
        # Interactive
        ClarifyTool(),
        # ClarAIty Knowledge DB (knowledge_query is the unified read tool)
        KnowledgeScanFilesTool(),
        KnowledgeUpdateTool(),
        KnowledgeQueryTool(),
        KnowledgeSetMetadataTool(),
        KnowledgeAutoLayoutTool(),
        KnowledgeExportTool(),
        # ClarAIty Beads
        BeadReadyTool(),
        BeadCreateTool(),
        BeadUpdateTool(),
        BeadBlockTool(),
        # Web tools (basic, no rate limiting — agent overrides with budgeted versions)
        WebSearchTool(),
        WebFetchTool(),
    ]
