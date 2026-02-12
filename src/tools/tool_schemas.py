"""
Tool schemas for OpenAI-compatible function calling.

This module defines all available tools in OpenAI's function calling format.
These schemas are used by the LLM to understand what tools are available and how to call them.
"""

from typing import List, Optional
from src.llm.base import ToolDefinition


# File Operations Tools

READ_FILE_TOOL = ToolDefinition(
    name="read_file",
    description="Read file contents with streaming line-range support. For large files, use start_line/end_line/max_lines to read in chunks. Returns content with line numbers (cat -n format). THIS IS YOUR PRIMARY TOOL for understanding any file.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read"
            },
            "start_line": {
                "type": "integer",
                "description": "Start line number (1-indexed, inclusive). Default: 1"
            },
            "end_line": {
                "type": "integer",
                "description": "End line number (1-indexed, EXCLUSIVE). Default: start_line + max_lines"
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum lines to return (default: 1000, limit: 2000 per read)."
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

APPEND_TO_FILE_TOOL = ToolDefinition(
    name="append_to_file",
    description="Append content to an existing file (or create if doesn't exist). Use for building large files incrementally or adding new sections to existing files.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to append to (creates if doesn't exist)"
            },
            "content": {
                "type": "string",
                "description": "Content to append to the file. Will be added at the end with proper newline handling."
            }
        },
        "required": ["file_path", "content"]
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
    description="Analyze code structure (classes, functions, imports) using AST parsing. NOTE: Only use AFTER read_file if you need structured metadata. For understanding a file, read_file alone is usually sufficient.",
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

# Enhanced Search Tools (ripgrep-like capabilities)

GREP_TOOL = ToolDefinition(
    name="grep",
    description="Advanced regex search with file type filters, context lines, and multiple output modes. Production-grade search matching ripgrep capabilities. Use for finding code patterns, error handling, TODOs, etc.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for (e.g., '^class \w+', 'TODO|FIXME', 'def authenticate')"
            },
            "path": {
                "type": "string",
                "description": "File or directory to search (default: current directory)"
            },
            "file_type": {
                "type": "string",
                "description": "File type filter: 'py', 'js', 'ts', 'java', 'cpp', 'go', 'rust', etc."
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g., '*.py', 'src/**/*.ts')"
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "'content' (show matching lines), 'files_with_matches' (file paths only), 'count' (match counts per file)"
            },
            "context_before": {
                "type": "number",
                "description": "Lines of context before match (like -B)"
            },
            "context_after": {
                "type": "number",
                "description": "Lines of context after match (like -A)"
            },
            "context": {
                "type": "number",
                "description": "Lines of context before AND after match (like -C)"
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Ignore case when searching (like -i)"
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Show line numbers in output (default: true for content mode)"
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline matching (pattern can span lines)"
            },
            "head_limit": {
                "type": "number",
                "description": "Limit output to first N results"
            },
            "offset": {
                "type": "number",
                "description": "Skip first N results"
            }
        },
        "required": ["pattern"]
    }
)

GLOB_TOOL = ToolDefinition(
    name="glob",
    description="Fast file pattern matching with recursive search. Find files by glob patterns (e.g., **/*.py, src/**/*.{ts,tsx}). Returns sorted by modification time.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g., '*.py', '**/*.js', 'src/**/*.{ts,tsx}' for brace expansion)"
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)"
            },
            "sort_by_mtime": {
                "type": "boolean",
                "description": "Sort results by modification time, newest first (default: true)"
            }
        },
        "required": ["pattern"]
    }
)

# LSP-Based Semantic Code Analysis Tools

GET_FILE_OUTLINE_TOOL = ToolDefinition(
    name="get_file_outline",
    description="Get file structure (classes, functions, methods) using LSP semantic analysis. WARNING: May fail for unsupported languages (Java, C++, etc.) - if it fails, fall back to read_file immediately (do NOT retry). For most tasks, read_file is sufficient and more reliable.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to file to analyze (e.g., 'src/core/agent.py', 'lib/utils.ts')"
            }
        },
        "required": ["file_path"]
    }
)

GET_SYMBOL_CONTEXT_TOOL = ToolDefinition(
    name="get_symbol_context",
    description="Get complete symbol details by name using LSP. WARNING: LSP may not support all languages - if it fails, use grep + read_file instead. Returns signature, docstring, implementation, and references.",
    parameters={
        "type": "object",
        "properties": {
            "symbol_name": {
                "type": "string",
                "description": "Symbol name to search for (e.g., 'authenticate', 'User', 'parse_config', 'LSPClientManager')"
            },
            "file_hint": {
                "type": "string",
                "description": "Optional file path hint to narrow search (e.g., 'auth.py', 'src/core/', 'models/user.py'). Use when symbol appears in multiple files."
            },
            "include_references": {
                "type": "boolean",
                "description": "Include where symbol is used/called (default: true). Set false for faster queries."
            },
            "include_implementation": {
                "type": "boolean",
                "description": "Include actual code implementation (default: true). Set false if you only need signature/location."
            }
        },
        "required": ["symbol_name"]
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
    description="Delegate a task to a specialized subagent for focused execution. Subagents have independent context (no pollution of main conversation). Available: code-reviewer, test-writer, doc-writer.",
    parameters={
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
)

TODO_WRITE_TOOL = ToolDefinition(
    name="todo_write",
    description="Create and update a task list to track progress through multi-step work. Use for complex tasks with 3+ steps.",
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Array of todo items",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Task description (imperative: 'Fix bug')"
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous form ('Fixing bug')"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Task status"
                        }
                    },
                    "required": ["content", "status", "activeForm"]
                }
            }
        },
        "required": ["todos"]
    }
)

CREATE_CHECKPOINT_TOOL = ToolDefinition(
    name="create_checkpoint",
    description="Save current work to a checkpoint (save point for long-running sessions). Use at logical stopping points: module complete, tests passing, major milestone achieved, before risky changes, etc. This allows resuming work later if interrupted.",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What was accomplished in this session (e.g., 'Completed authentication module', 'Fixed memory leak in context builder')"
            },
            "current_phase": {
                "type": "string",
                "description": "Optional: Current development phase (e.g., 'Phase 1', 'Phase 0.4')"
            },
            "pending_tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: List of tasks remaining to complete"
            }
        },
        "required": ["description"]
    }
)


# ClarAIty Architecture Query Tools

QUERY_COMPONENT_TOOL = ToolDefinition(
    name="query_component",
    description="Query detailed information about a specific architectural component. Returns component details, design decisions, code artifacts, and relationships.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to query (e.g., 'CODING_AGENT', 'OBSERVABILITY_LAYER', 'CLARITY_INTEGRATION')"
            }
        },
        "required": ["component_id"]
    }
)

QUERY_DEPENDENCIES_TOOL = ToolDefinition(
    name="query_dependencies",
    description="Query component dependencies and relationships. Returns both incoming (who uses this component) and outgoing (what this component depends on) relationships.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to query relationships for"
            }
        },
        "required": ["component_id"]
    }
)

QUERY_DECISIONS_TOOL = ToolDefinition(
    name="query_decisions",
    description="Query design decisions for a component or globally. Returns decisions with rationale, alternatives considered, and trade-offs.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to query decisions for. If not provided, returns all decisions."
            }
        },
        "required": []
    }
)

QUERY_FLOWS_TOOL = ToolDefinition(
    name="query_flows",
    description="Query execution flows in the system. Returns flow details with steps, triggers, and component involvement.",
    parameters={
        "type": "object",
        "properties": {
            "flow_id": {
                "type": "string",
                "description": "Flow ID to query. If not provided, returns all flows."
            }
        },
        "required": []
    }
)

QUERY_ARCHITECTURE_SUMMARY_TOOL = ToolDefinition(
    name="query_architecture_summary",
    description="Query architecture overview organized by layer. Returns component counts, status breakdown, and progress for each layer.",
    parameters={
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Optional layer filter (core, execution, tools, llm, memory, rag, etc.)"
            }
        },
        "required": []
    }
)

SEARCH_COMPONENTS_TOOL = ToolDefinition(
    name="search_components",
    description="Search components by keyword in name, purpose, or business value. Useful for discovering relevant components.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'testing', 'memory', 'error handling')"
            }
        },
        "required": ["query"]
    }
)

CLARITY_SETUP_TOOL = ToolDefinition(
    name="clarity_setup",
    description="Initialize ClarAIty database by scanning the current project codebase. Use when ClarAIty DB doesn't exist or needs updating. Analyzes Python files to extract components, relationships, and architecture.",
    parameters={
        "type": "object",
        "properties": {
            "rescan": {
                "type": "boolean",
                "description": "If true, force full rescan even if database exists. Use when codebase has changed significantly."
            }
        },
        "required": []
    }
)

GET_NEXT_TASK_TOOL = ToolDefinition(
    name="get_next_task",
    description="Get the next planned component to work on (prioritizes Phase 0 components). Returns component details, dependencies, and action to take. Use at the start of every session.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)

UPDATE_COMPONENT_STATUS_TOOL = ToolDefinition(
    name="update_component_status",
    description="Update the status of a component (planned → in_progress → completed). Use when starting work (in_progress) and when finishing (completed). Returns phase progress percentage.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to update (e.g., 'LLM_FAILURE_HANDLER', 'AGENT_INTERFACE')"
            },
            "new_status": {
                "type": "string",
                "description": "New status: 'planned', 'in_progress', or 'completed'",
                "enum": ["planned", "in_progress", "completed"]
            }
        },
        "required": ["component_id", "new_status"]
    }
)

ADD_ARTIFACT_TOOL = ToolDefinition(
    name="add_artifact",
    description="Track a file created or modified for a component. Auto-detects artifact type and language from file extension. Use after creating/modifying files.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID this artifact belongs to"
            },
            "file_path": {
                "type": "string",
                "description": "Path to the file (relative or absolute)"
            },
            "description": {
                "type": "string",
                "description": "Optional description of what this file does. If not provided, uses filename."
            }
        },
        "required": ["component_id", "file_path"]
    }
)

GET_IMPLEMENTATION_SPEC_TOOL = ToolDefinition(
    name="get_implementation_spec",
    description="Get detailed implementation specification for a component. Returns method signatures with parameters, acceptance criteria (definition of done), implementation patterns, and code examples. Use for complex components to get complete implementation guidance.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to get implementation spec for (e.g., 'LLM_FAILURE_HANDLER', 'AGENT_INTERFACE')"
            }
        },
        "required": ["component_id"]
    }
)

ADD_METHOD_TOOL = ToolDefinition(
    name="add_method",
    description="Add a method signature to a component's implementation spec. Use to document methods that need to be implemented.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to add method to"
            },
            "method_name": {
                "type": "string",
                "description": "Method name (e.g., 'call_llm', 'handle_timeout')"
            },
            "signature": {
                "type": "string",
                "description": "Full method signature (e.g., 'call_llm(self, messages: List[Dict], **kwargs) -> str')"
            },
            "description": {
                "type": "string",
                "description": "Description of what the method does"
            },
            "parameters": {
                "type": "array",
                "description": "Optional list of parameter objects with name, type, description, required, default"
            },
            "return_type": {
                "type": "string",
                "description": "Optional return type annotation"
            },
            "raises": {
                "type": "array",
                "description": "Optional list of exception names this method can raise"
            },
            "example_usage": {
                "type": "string",
                "description": "Optional usage example"
            }
        },
        "required": ["component_id", "method_name", "signature", "description"]
    }
)

ADD_ACCEPTANCE_CRITERION_TOOL = ToolDefinition(
    name="add_acceptance_criterion",
    description="Add an acceptance criterion to a component (definition of done). Use to specify test coverage, integration requirements, performance targets, etc.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID to add criterion to"
            },
            "criteria_type": {
                "type": "string",
                "description": "Type of criterion (e.g., 'test_coverage', 'integration', 'performance', 'breaking_changes')"
            },
            "description": {
                "type": "string",
                "description": "Description of the criterion"
            },
            "target_value": {
                "type": "string",
                "description": "Optional target value (e.g., '90%', '< 100ms', '0 breaking changes')"
            },
            "validation_method": {
                "type": "string",
                "description": "Optional validation method (e.g., 'pytest --cov', 'Manual verification')"
            },
            "priority": {
                "type": "string",
                "description": "Priority: 'required', 'recommended', or 'optional' (default: required)",
                "enum": ["required", "recommended", "optional"]
            }
        },
        "required": ["component_id", "criteria_type", "description"]
    }
)

UPDATE_METHOD_TOOL = ToolDefinition(
    name="update_method",
    description="Update an existing method specification. Use to refine signatures, parameters, or examples based on implementation learnings.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID containing the method"
            },
            "method_name": {
                "type": "string",
                "description": "Method name to update (must exist)"
            },
            "signature": {
                "type": "string",
                "description": "Optional: New method signature"
            },
            "description": {
                "type": "string",
                "description": "Optional: New description"
            },
            "parameters": {
                "type": "array",
                "description": "Optional: New parameter list"
            },
            "return_type": {
                "type": "string",
                "description": "Optional: New return type"
            },
            "raises": {
                "type": "array",
                "description": "Optional: New exception list"
            },
            "example_usage": {
                "type": "string",
                "description": "Optional: New usage example"
            }
        },
        "required": ["component_id", "method_name"]
    }
)

UPDATE_ACCEPTANCE_CRITERION_TOOL = ToolDefinition(
    name="update_acceptance_criterion",
    description="Update an existing acceptance criterion. Use to adjust targets, validation methods, or priorities based on implementation learnings.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID containing the criterion"
            },
            "criteria_type": {
                "type": "string",
                "description": "Criterion type to update (e.g., 'test_coverage', 'integration')"
            },
            "description": {
                "type": "string",
                "description": "Optional: New description"
            },
            "target_value": {
                "type": "string",
                "description": "Optional: New target value (e.g., '95%', '< 50ms')"
            },
            "validation_method": {
                "type": "string",
                "description": "Optional: New validation method"
            },
            "priority": {
                "type": "string",
                "description": "Optional: New priority (required/recommended/optional)",
                "enum": ["required", "recommended", "optional"]
            },
            "status": {
                "type": "string",
                "description": "Optional: New status (pending/met/not_met)",
                "enum": ["pending", "met", "not_met"]
            }
        },
        "required": ["component_id", "criteria_type"]
    }
)

UPDATE_IMPLEMENTATION_PATTERN_TOOL = ToolDefinition(
    name="update_implementation_pattern",
    description="Update an existing implementation pattern. Use to refine code examples, add antipatterns, or update references based on implementation learnings.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID containing the pattern"
            },
            "pattern_name": {
                "type": "string",
                "description": "Pattern name to update (must exist)"
            },
            "pattern_type": {
                "type": "string",
                "description": "Optional: New pattern type (e.g., 'workflow', 'error_handling')"
            },
            "description": {
                "type": "string",
                "description": "Optional: New description (why use this pattern)"
            },
            "code_example": {
                "type": "string",
                "description": "Optional: New code example"
            },
            "antipatterns": {
                "type": "string",
                "description": "Optional: New antipatterns (what NOT to do)"
            },
            "reference_links": {
                "type": "string",
                "description": "Optional: New reference links"
            }
        },
        "required": ["component_id", "pattern_name"]
    }
)

# Testing & Validation Tools

RUN_TESTS_TOOL = ToolDefinition(
    name="run_tests",
    description="Run tests autonomously and get feedback on failures. Auto-detects test framework (pytest, jest, vitest, cargo) and generates LLM-powered fix suggestions for failures.",
    parameters={
        "type": "object",
        "properties": {
            "framework": {
                "type": "string",
                "description": "Optional: Override framework detection (pytest, jest, vitest, cargo)",
                "enum": ["pytest", "jest", "vitest", "cargo"]
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional: Test file pattern to filter tests (e.g., 'tests/test_auth.py')"
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: List of changed files for validation context"
            }
        },
        "required": []
    }
)

DETECT_TEST_FRAMEWORK_TOOL = ToolDefinition(
    name="detect_test_framework",
    description="Detect test framework from project files (pytest.ini, package.json, Cargo.toml, etc.). Returns framework name or None if not detected.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)


# Web Tools

WEB_SEARCH_TOOL = ToolDefinition(
    name="web_search",
    description="Search the web for current information. Returns results with citations. Use for: documentation, error messages, library versions, best practices, current events.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'Python 3.12 new features', 'React 19 hooks')"
            },
            "max_results": {
                "type": "number",
                "description": "Results to return (1-10, default: 5)"
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "'basic' (fast) or 'advanced' (thorough). Default: basic"
            },
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only include results from these domains (e.g., ['github.com', 'stackoverflow.com'])"
            },
            "exclude_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude results from these domains"
            }
        },
        "required": ["query"]
    }
)

WEB_FETCH_TOOL = ToolDefinition(
    name="web_fetch",
    description="Fetch content from a specific URL. Returns extracted text. Use after web_search or for known documentation URLs. Supports text/html, JSON, XML only.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch (http/https only, ports 80/443)"
            },
            "extract_text": {
                "type": "boolean",
                "description": "Extract plain text from HTML (default: true)"
            }
        },
        "required": ["url"]
    }
)


# Plan Mode Tools - Enter/exit plan mode for structured planning workflow

ENTER_PLAN_MODE_TOOL = ToolDefinition(
    name="enter_plan_mode",
    description="Enter plan mode to design an implementation approach before making changes. Creates a plan file where you write your implementation plan. While in plan mode, only read-only tools are available (plus writing to the plan file). Use for complex tasks that benefit from upfront planning.",
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief reason for entering plan mode (e.g., 'Complex refactoring with multiple dependencies')"
            }
        },
        "required": []
    }
)

EXIT_PLAN_MODE_TOOL = ToolDefinition(
    name="exit_plan_mode",
    description="Exit plan mode and submit your plan for user approval. Call this after writing your implementation plan to the plan file. The user will review the plan and approve or request changes.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)


# Clarify Tool - Ask user structured questions before proceeding with ambiguous tasks

CLARIFY_TOOL = ToolDefinition(
    name="clarify",
    description="Ask the user clarifying questions before proceeding with ambiguous tasks. Use this when the task is unclear, has multiple valid approaches, or requires user preference. Provides a structured interview interface with 1-4 questions.",
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "description": "Questions to ask (1-4 questions)",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier for this question (e.g., 'approach', 'framework')"
                        },
                        "label": {
                            "type": "string",
                            "description": "Short tab label (max 12 chars, e.g., 'Approach', 'Framework')"
                        },
                        "question": {
                            "type": "string",
                            "description": "The full question text to display"
                        },
                        "options": {
                            "type": "array",
                            "minItems": 1,
                            "description": "Available answer options",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Unique identifier for this option"
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Short option label"
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Detailed description of this option"
                                    },
                                    "recommended": {
                                        "type": "boolean",
                                        "description": "Mark this option as recommended (shows '(Recommended)' tag)"
                                    }
                                },
                                "required": ["id", "label"]
                            }
                        },
                        "multi_select": {
                            "type": "boolean",
                            "description": "Allow multiple options to be selected (default: false)"
                        },
                        "allow_custom": {
                            "type": "boolean",
                            "description": "Allow user to type a custom response (default: false)"
                        }
                    },
                    "required": ["id", "label", "question", "options"]
                }
            },
            "context": {
                "type": "string",
                "description": "Brief explanation of why clarification is needed (shown to user)"
            }
        },
        "required": ["questions"]
    }
)


# Tool Collections

ALL_TOOLS = [
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    APPEND_TO_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    RUN_COMMAND_TOOL,
    SEARCH_CODE_TOOL,
    ANALYZE_CODE_TOOL,
    GREP_TOOL,
    GLOB_TOOL,
    GET_FILE_OUTLINE_TOOL,
    GET_SYMBOL_CONTEXT_TOOL,
    GIT_STATUS_TOOL,
    GIT_DIFF_TOOL,
    GIT_COMMIT_TOOL,
    DELEGATE_TO_SUBAGENT_TOOL,
    TODO_WRITE_TOOL,
    CREATE_CHECKPOINT_TOOL,
    QUERY_COMPONENT_TOOL,
    QUERY_DEPENDENCIES_TOOL,
    QUERY_DECISIONS_TOOL,
    QUERY_FLOWS_TOOL,
    QUERY_ARCHITECTURE_SUMMARY_TOOL,
    SEARCH_COMPONENTS_TOOL,
    CLARITY_SETUP_TOOL,
    GET_NEXT_TASK_TOOL,
    UPDATE_COMPONENT_STATUS_TOOL,
    ADD_ARTIFACT_TOOL,
    GET_IMPLEMENTATION_SPEC_TOOL,
    ADD_METHOD_TOOL,
    ADD_ACCEPTANCE_CRITERION_TOOL,
    UPDATE_METHOD_TOOL,
    UPDATE_ACCEPTANCE_CRITERION_TOOL,
    UPDATE_IMPLEMENTATION_PATTERN_TOOL,
    RUN_TESTS_TOOL,
    DETECT_TEST_FRAMEWORK_TOOL,
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    CLARIFY_TOOL,
    ENTER_PLAN_MODE_TOOL,
    EXIT_PLAN_MODE_TOOL,
]

PLAN_MODE_TOOLS = [
    ENTER_PLAN_MODE_TOOL,
    EXIT_PLAN_MODE_TOOL,
]

WEB_TOOLS = [
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
]

FILE_TOOLS = [
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    APPEND_TO_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
]

CODE_TOOLS = [
    SEARCH_CODE_TOOL,
    ANALYZE_CODE_TOOL,
    GREP_TOOL,
    GLOB_TOOL,
    GET_FILE_OUTLINE_TOOL,
    GET_SYMBOL_CONTEXT_TOOL,
]

GIT_TOOLS = [
    GIT_STATUS_TOOL,
    GIT_DIFF_TOOL,
    GIT_COMMIT_TOOL,
]

EXECUTION_TOOLS = [
    RUN_COMMAND_TOOL,
]

TESTING_TOOLS = [
    RUN_TESTS_TOOL,
    DETECT_TEST_FRAMEWORK_TOOL,
]

CLARITY_TOOLS = [
    QUERY_COMPONENT_TOOL,
    QUERY_DEPENDENCIES_TOOL,
    QUERY_DECISIONS_TOOL,
    QUERY_FLOWS_TOOL,
    QUERY_ARCHITECTURE_SUMMARY_TOOL,
    SEARCH_COMPONENTS_TOOL,
    CLARITY_SETUP_TOOL,
    GET_NEXT_TASK_TOOL,
    UPDATE_COMPONENT_STATUS_TOOL,
    ADD_ARTIFACT_TOOL,
    GET_IMPLEMENTATION_SPEC_TOOL,
    ADD_METHOD_TOOL,
    ADD_ACCEPTANCE_CRITERION_TOOL,
    UPDATE_METHOD_TOOL,
    UPDATE_ACCEPTANCE_CRITERION_TOOL,
    UPDATE_IMPLEMENTATION_PATTERN_TOOL,
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


def get_all_tools(
    mcp_definitions: Optional[List[ToolDefinition]] = None,
) -> List[ToolDefinition]:
    """Return native tools merged with any active MCP tool definitions.

    This is the single function that builds the tool list for LLM requests.
    Native tools come first (stable ordering), MCP tools are appended.

    Args:
        mcp_definitions: Optional list of MCP-provided ToolDefinitions
                        (from McpToolRegistry.get_tool_definitions()).

    Returns:
        Combined list of ToolDefinitions.
    """
    if not mcp_definitions:
        return list(ALL_TOOLS)
    return list(ALL_TOOLS) + list(mcp_definitions)


__all__ = [
    "READ_FILE_TOOL",
    "WRITE_FILE_TOOL",
    "EDIT_FILE_TOOL",
    "APPEND_TO_FILE_TOOL",
    "LIST_DIRECTORY_TOOL",
    "RUN_COMMAND_TOOL",
    "SEARCH_CODE_TOOL",
    "ANALYZE_CODE_TOOL",
    "GIT_STATUS_TOOL",
    "GIT_DIFF_TOOL",
    "GIT_COMMIT_TOOL",
    "DELEGATE_TO_SUBAGENT_TOOL",
    "TODO_WRITE_TOOL",
    "CREATE_CHECKPOINT_TOOL",
    "QUERY_COMPONENT_TOOL",
    "QUERY_DEPENDENCIES_TOOL",
    "QUERY_DECISIONS_TOOL",
    "QUERY_FLOWS_TOOL",
    "QUERY_ARCHITECTURE_SUMMARY_TOOL",
    "SEARCH_COMPONENTS_TOOL",
    "CLARITY_SETUP_TOOL",
    "ALL_TOOLS",
    "FILE_TOOLS",
    "CODE_TOOLS",
    "GIT_TOOLS",
    "EXECUTION_TOOLS",
    "CLARITY_TOOLS",
    "CLARIFY_TOOL",
    "ENTER_PLAN_MODE_TOOL",
    "EXIT_PLAN_MODE_TOOL",
    "PLAN_MODE_TOOLS",
    "get_tools_for_task",
    "get_all_tools",
]
