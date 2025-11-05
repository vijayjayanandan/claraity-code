"""
Tool schemas for OpenAI-compatible function calling.

This module defines all available tools in OpenAI's function calling format.
These schemas are used by the LLM to understand what tools are available and how to call them.
"""

from typing import List
from src.llm.base import ToolDefinition


# File Operations Tools

READ_FILE_TOOL = ToolDefinition(
    name="read_file",
    description="Read the contents of a file from the filesystem",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read"
            }
        },
        "required": ["file_path"]
    }
)

WRITE_FILE_TOOL = ToolDefinition(
    name="write_file",
    description="Create a new file with the specified content. Use this for NEW files only (not editing existing files).",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path where the file should be created"
            },
            "content": {
                "type": "string",
                "description": "Full content to write to the file. Keep under 100 lines if possible - break large files into skeleton + edits."
            }
        },
        "required": ["file_path", "content"]
    }
)

EDIT_FILE_TOOL = ToolDefinition(
    name="edit_file",
    description="Edit an existing file by replacing specific text. Use exact text matching - the old_text must match exactly (including whitespace).",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit"
            },
            "old_text": {
                "type": "string",
                "description": "Exact text to find and replace (must match exactly including whitespace)"
            },
            "new_text": {
                "type": "string",
                "description": "New text to replace the old text with"
            }
        },
        "required": ["file_path", "old_text", "new_text"]
    }
)

LIST_DIRECTORY_TOOL = ToolDefinition(
    name="list_directory",
    description="List all files and subdirectories in a directory",
    parameters={
        "type": "object",
        "properties": {
            "directory_path": {
                "type": "string",
                "description": "Path to the directory to list"
            }
        },
        "required": ["directory_path"]
    }
)

RUN_COMMAND_TOOL = ToolDefinition(
    name="run_command",
    description="Execute a shell command and return its output. Use for testing, building, running scripts, etc.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute (e.g., 'python test.py', 'npm install', 'pytest')"
            },
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds (default: 30s)"
            }
        },
        "required": ["command"]
    }
)


# Code Search & Analysis Tools

SEARCH_CODE_TOOL = ToolDefinition(
    name="search_code",
    description="Search for code patterns using semantic and keyword search. Returns relevant code snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'function that handles user auth', 'error handling')"
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional file pattern to filter results (e.g., '*.py', 'src/**/*.ts')"
            }
        },
        "required": ["query"]
    }
)

ANALYZE_CODE_TOOL = ToolDefinition(
    name="analyze_code",
    description="Analyze code structure (classes, functions, imports) using AST parsing",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to analyze"
            }
        },
        "required": ["file_path"]
    }
)


# Git Operations Tools

GIT_STATUS_TOOL = ToolDefinition(
    name="git_status",
    description="Get git status - shows modified, staged, and untracked files",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)

GIT_DIFF_TOOL = ToolDefinition(
    name="git_diff",
    description="View git diff - shows changes in modified files",
    parameters={
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "If true, show diff of staged changes. If false, show unstaged changes."
            }
        },
        "required": []
    }
)

GIT_COMMIT_TOOL = ToolDefinition(
    name="git_commit",
    description="Create a git commit with the specified message",
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message describing the changes"
            }
        },
        "required": ["message"]
    }
)


# Delegation Tool

DELEGATE_TO_SUBAGENT_TOOL = ToolDefinition(
    name="delegate_to_subagent",
    description="Delegate a complex subtask to an independent subagent. Use for large, self-contained tasks.",
    parameters={
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Clear description of the subtask to delegate"
            },
            "context": {
                "type": "string",
                "description": "Additional context the subagent needs"
            }
        },
        "required": ["task_description"]
    }
)


# Tool Collections

ALL_TOOLS = [
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    RUN_COMMAND_TOOL,
    SEARCH_CODE_TOOL,
    ANALYZE_CODE_TOOL,
    GIT_STATUS_TOOL,
    GIT_DIFF_TOOL,
    GIT_COMMIT_TOOL,
    DELEGATE_TO_SUBAGENT_TOOL,
]

FILE_TOOLS = [
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
]

CODE_TOOLS = [
    SEARCH_CODE_TOOL,
    ANALYZE_CODE_TOOL,
]

GIT_TOOLS = [
    GIT_STATUS_TOOL,
    GIT_DIFF_TOOL,
    GIT_COMMIT_TOOL,
]

EXECUTION_TOOLS = [
    RUN_COMMAND_TOOL,
]


def get_tools_for_task(task_type: str) -> List[ToolDefinition]:
    """
    Get relevant tools based on task type.

    Args:
        task_type: Type of task (feature, bug_fix, refactor, etc.)

    Returns:
        List of relevant tool definitions
    """
    # For most tasks, return all tools
    # Can be refined later based on task analysis
    return ALL_TOOLS


__all__ = [
    "READ_FILE_TOOL",
    "WRITE_FILE_TOOL",
    "EDIT_FILE_TOOL",
    "LIST_DIRECTORY_TOOL",
    "RUN_COMMAND_TOOL",
    "SEARCH_CODE_TOOL",
    "ANALYZE_CODE_TOOL",
    "GIT_STATUS_TOOL",
    "GIT_DIFF_TOOL",
    "GIT_COMMIT_TOOL",
    "DELEGATE_TO_SUBAGENT_TOOL",
    "ALL_TOOLS",
    "FILE_TOOLS",
    "CODE_TOOLS",
    "GIT_TOOLS",
    "EXECUTION_TOOLS",
    "get_tools_for_task",
]
