"""
Tool schemas for OpenAI-compatible function calling.

This module defines all available tools in OpenAI's function calling format.
These schemas are used by the LLM to understand what tools are available and how to call them.
"""

from typing import Optional

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
                "description": "Absolute or relative path to the file to read",
            },
            "start_line": {
                "type": "integer",
                "description": "Start line number (1-indexed, inclusive). Default: 1",
            },
            "end_line": {
                "type": "integer",
                "description": "End line number (1-indexed, EXCLUSIVE). Default: start_line + max_lines",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum lines to return (default: 1000, limit: 2000 per read).",
            },
        },
        "required": ["file_path"],
    },
)

WRITE_FILE_TOOL = ToolDefinition(
    name="write_file",
    description="Create a new file with the specified content. Use this for NEW files only (not editing existing files).",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path where the file should be created"},
            "content": {
                "type": "string",
                "description": "Full content to write to the file. Keep under 100 lines if possible - break large files into skeleton + edits.",
            },
        },
        "required": ["file_path", "content"],
    },
)

EDIT_FILE_TOOL = ToolDefinition(
    name="edit_file",
    description="Edit an existing file by replacing specific text. Use exact text matching - the old_text must match exactly (including whitespace).",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "old_text": {
                "type": "string",
                "description": "Exact text to find and replace (must match exactly including whitespace)",
            },
            "new_text": {"type": "string", "description": "New text to replace the old text with"},
        },
        "required": ["file_path", "old_text", "new_text"],
    },
)

APPEND_TO_FILE_TOOL = ToolDefinition(
    name="append_to_file",
    description="Append content to an existing file (or create if doesn't exist). Use for building large files incrementally or adding new sections to existing files.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to append to (creates if doesn't exist)",
            },
            "content": {
                "type": "string",
                "description": "Content to append to the file. Will be added at the end with proper newline handling.",
            },
        },
        "required": ["file_path", "content"],
    },
)

LIST_DIRECTORY_TOOL = ToolDefinition(
    name="list_directory",
    description="list all files and subdirectories in a directory",
    parameters={
        "type": "object",
        "properties": {
            "directory_path": {"type": "string", "description": "Path to the directory to list"}
        },
        "required": ["directory_path"],
    },
)

RUN_COMMAND_TOOL = ToolDefinition(
    name="run_command",
    description=(
        "Execute a shell command and return its output. "
        "Use for running tests, building projects, executing scripts, package management, and git operations.\n\n"
        "IMPORTANT - Shell environment:\n"
        "- On Windows, commands run in PowerShell 5.1 (NOT cmd.exe, NOT bash).\n"
        "- Do NOT use '&&' to chain commands -- PowerShell 5.1 does not support it. Use '; ' (semicolon) instead.\n"
        "- Do NOT use 'cd /d' -- that is cmd.exe syntax. PowerShell uses 'Set-Location' or just 'cd'.\n"
        "- Prefer the working_directory parameter over 'cd' commands.\n"
        "- On Unix/macOS, commands run in the default shell (bash/zsh).\n\n"
        "Do NOT use run_command for:\n"
        "- Reading files (use read_file)\n"
        "- Searching code (use grep or glob)\n"
        "- Editing files (use edit_file)\n"
        "- Listing directories (use list_directory)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute (e.g., 'python test.py', 'npm install', 'pytest tests/ -v')",
            },
            "description": {
                "type": "string",
                "description": "Brief description of what this command does (e.g., 'Run unit tests', 'Install dependencies'). Helps with auditability.",
            },
            "working_directory": {
                "type": "string",
                "description": "Directory to run the command in. Use this instead of 'cd' commands. Must be a valid existing directory path.",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default: 120). Use higher values for long-running commands like test suites or builds (max: 600)",
            },
            "background": {
                "type": "boolean",
                "description": (
                    "Set true to run in background (non-blocking). Returns immediately with a task ID. "
                    "You will be automatically notified via a [BACKGROUND TASK UPDATE] message when the "
                    "task completes. Use for long-running operations like test suites, builds, or linters "
                    "while you continue other work."
                ),
            },
        },
        "required": ["command"],
    },
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
                "description": r"Regex pattern to search for (e.g., '^class \w+', 'TODO|FIXME', 'def authenticate')",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search (default: current directory)",
            },
            "file_type": {
                "type": "string",
                "description": "File type filter: 'py', 'js', 'ts', 'java', 'cpp', 'go', 'rust', etc.",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g., '*.py', 'src/**/*.ts')",
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "'content' (show matching lines), 'files_with_matches' (file paths only), 'count' (match counts per file)",
            },
            "context_before": {
                "type": "number",
                "description": "Lines of context before match (like -B)",
            },
            "context_after": {
                "type": "number",
                "description": "Lines of context after match (like -A)",
            },
            "context": {
                "type": "number",
                "description": "Lines of context before AND after match (like -C)",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Ignore case when searching (like -i)",
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Show line numbers in output (default: true for content mode)",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline matching (pattern can span lines)",
            },
            "head_limit": {"type": "number", "description": "Limit output to first N results"},
            "offset": {"type": "number", "description": "Skip first N results"},
        },
        "required": ["pattern"],
    },
)

GLOB_TOOL = ToolDefinition(
    name="glob",
    description="Fast file pattern matching with recursive search. Find files by glob patterns (e.g., **/*.py, src/**/*.{ts,tsx}). Returns sorted by modification time.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g., '*.py', '**/*.js', 'src/**/*.{ts,tsx}' for brace expansion)",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
            },
            "sort_by_mtime": {
                "type": "boolean",
                "description": "Sort results by modification time, newest first (default: true)",
            },
        },
        "required": ["pattern"],
    },
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
                "description": "Path to file to analyze (e.g., 'src/core/agent.py', 'lib/utils.ts')",
            }
        },
        "required": ["file_path"],
    },
)

GET_SYMBOL_CONTEXT_TOOL = ToolDefinition(
    name="get_symbol_context",
    description="Get complete symbol details by name using LSP. WARNING: LSP may not support all languages - if it fails, use grep + read_file instead. Returns signature, docstring, implementation, and references.",
    parameters={
        "type": "object",
        "properties": {
            "symbol_name": {
                "type": "string",
                "description": "Symbol name to search for (e.g., 'authenticate', 'User', 'parse_config', 'LSPClientManager')",
            },
            "file_hint": {
                "type": "string",
                "description": "Optional file path hint to narrow search (e.g., 'auth.py', 'src/core/', 'models/user.py'). Use when symbol appears in multiple files.",
            },
            "include_references": {
                "type": "boolean",
                "description": "Include where symbol is used/called (default: true). Set false for faster queries.",
            },
            "include_implementation": {
                "type": "boolean",
                "description": "Include actual code implementation (default: true). Set false if you only need signature/location.",
            },
        },
        "required": ["symbol_name"],
    },
)


# Delegation Tool

DELEGATE_TO_SUBAGENT_TOOL = ToolDefinition(
    name="delegate_to_subagent",
    description="Delegate a task to a specialized subagent for focused execution. Subagents have independent context (no pollution of main conversation). Available: code-writer, code-reviewer, test-writer, doc-writer, explore, planner, general-purpose.",
    parameters={
        "type": "object",
        "properties": {
            "subagent": {
                "type": "string",
                "description": "Name of the subagent: 'code-writer' (implement code), 'test-writer' (write tests), 'code-reviewer' (review quality), 'explore' (read-only codebase search), 'planner' (design plans), 'doc-writer' (documentation), 'general-purpose' (multi-step tasks)",
            },
            "task": {
                "type": "string",
                "description": "Clear, detailed description of the task to delegate to the subagent",
            },
        },
        "required": ["subagent", "task"],
    },
)

CREATE_CHECKPOINT_TOOL = ToolDefinition(
    name="create_checkpoint",
    description="Save current work to a checkpoint (save point for long-running sessions). Use at logical stopping points: module complete, tests passing, major milestone achieved, before risky changes, etc. This allows resuming work later if interrupted.",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What was accomplished in this session (e.g., 'Completed authentication module', 'Fixed memory leak in context builder')",
            },
            "current_phase": {
                "type": "string",
                "description": "Optional: Current development phase (e.g., 'Phase 1', 'Phase 0.4')",
            },
            "pending_tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: list of tasks remaining to complete",
            },
        },
        "required": ["description"],
    },
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
                "enum": ["pytest", "jest", "vitest", "cargo"],
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional: Test file pattern to filter tests (e.g., 'tests/test_auth.py')",
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: list of changed files for validation context",
            },
        },
        "required": [],
    },
)

DETECT_TEST_FRAMEWORK_TOOL = ToolDefinition(
    name="detect_test_framework",
    description="Detect test framework from project files (pytest.ini, package.json, Cargo.toml, etc.). Returns framework name or None if not detected.",
    parameters={"type": "object", "properties": {}, "required": []},
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
                "description": "Search query (e.g., 'Python 3.12 new features', 'React 19 hooks')",
            },
            "max_results": {
                "type": "number",
                "description": "Results to return (1-10, default: 5)",
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "'basic' (fast) or 'advanced' (thorough). Default: basic",
            },
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only include results from these domains (e.g., ['github.com', 'stackoverflow.com'])",
            },
            "exclude_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude results from these domains",
            },
        },
        "required": ["query"],
    },
)

WEB_FETCH_TOOL = ToolDefinition(
    name="web_fetch",
    description="Fetch content from a specific URL. Returns extracted text. Use after web_search or for known documentation URLs. Supports text/html, JSON, XML only.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch (http/https only, ports 80/443)",
            },
            "extract_text": {
                "type": "boolean",
                "description": "Extract plain text from HTML (default: true)",
            },
        },
        "required": ["url"],
    },
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
                "description": "Brief reason for entering plan mode (e.g., 'Complex refactoring with multiple dependencies')",
            }
        },
        "required": [],
    },
)

EXIT_PLAN_MODE_TOOL = ToolDefinition(
    name="request_plan_approval",
    description="Submit your implementation plan for user approval. Call this after writing your plan to the plan file. The user will review and either approve, reject, or request changes.",
    parameters={"type": "object", "properties": {}, "required": []},
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
                            "description": "Unique identifier for this question (e.g., 'approach', 'framework')",
                        },
                        "label": {
                            "type": "string",
                            "description": "Short tab label (max 12 chars, e.g., 'Approach', 'Framework')",
                        },
                        "question": {
                            "type": "string",
                            "description": "The full question text to display",
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
                                        "description": "Unique identifier for this option",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Short option label",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Detailed description of this option",
                                    },
                                    "recommended": {
                                        "type": "boolean",
                                        "description": "Mark this option as recommended (shows '(Recommended)' tag)",
                                    },
                                },
                                "required": ["id", "label"],
                            },
                        },
                        "multi_select": {
                            "type": "boolean",
                            "description": "Allow multiple options to be selected (default: false)",
                        },
                        "allow_custom": {
                            "type": "boolean",
                            "description": "Allow user to type a custom response (default: false)",
                        },
                    },
                    "required": ["id", "label", "question", "options"],
                },
            },
            "context": {
                "type": "string",
                "description": "Brief explanation of why clarification is needed (shown to user)",
            },
        },
        "required": ["questions"],
    },
)


# =============================================================================
# Director Mode Tools - Phase checkpoint tools for Director workflow
# =============================================================================

DIRECTOR_COMPLETE_UNDERSTAND_TOOL = ToolDefinition(
    name="director_complete_understand",
    description="Signal that the UNDERSTAND phase is complete. Submit your findings about the codebase and task. This is the ONLY way to advance from UNDERSTAND to PLAN phase.",
    parameters={
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Summary of the task being worked on",
            },
            "affected_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths that will be affected by this task",
            },
            "existing_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Patterns found in the codebase relevant to this task",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Constraints to respect during implementation",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Risks or potential issues identified",
            },
            "dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Dependencies relevant to this task",
            },
        },
        "required": ["task_description"],
    },
)

DIRECTOR_COMPLETE_PLAN_TOOL = ToolDefinition(
    name="director_complete_plan",
    description=(
        "Signal that the PLAN phase is complete. "
        "BEFORE calling this tool, write your full implementation plan "
        "(with rationale, decisions, trade-offs) to a markdown file using write_file "
        "at .clarity/plans/director_plan.md. Then call this tool with the file path "
        "and a list of slice titles for execution tracking."
    ),
    parameters={
        "type": "object",
        "properties": {
            "plan_document": {
                "type": "string",
                "description": "Path to the markdown plan file you wrote (e.g. .clarity/plans/director_plan.md)",
            },
            "summary": {
                "type": "string",
                "description": "Brief one-line summary of the plan",
            },
            "slices": {
                "type": "array",
                "description": "list of vertical slices for execution tracking (3-5 recommended)",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short name for this slice",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["plan_document", "slices"],
    },
)

DIRECTOR_COMPLETE_SLICE_TOOL = ToolDefinition(
    name="director_complete_slice",
    description="Signal that a vertical slice is complete and all its tests pass. This advances to the next slice or to INTEGRATE phase if all slices are done.",
    parameters={
        "type": "object",
        "properties": {
            "slice_id": {
                "type": "integer",
                "description": "ID of the completed slice",
            },
            "test_results_summary": {
                "type": "string",
                "description": "Summary of test results for this slice",
            },
        },
        "required": ["slice_id"],
    },
)

DIRECTOR_COMPLETE_INTEGRATION_TOOL = ToolDefinition(
    name="director_complete_integration",
    description="Signal that integration is complete -- all tests pass and all slices work together. This finishes Director mode.",
    parameters={
        "type": "object",
        "properties": {
            "test_results_summary": {
                "type": "string",
                "description": "Summary of the full test suite results",
            },
            "issues": {
                "type": "string",
                "description": "Any known issues or follow-up items (empty if none)",
            },
        },
        "required": [],
    },
)

# Background Task Tools

CHECK_BACKGROUND_TASK_TOOL = ToolDefinition(
    name="check_background_task",
    description=(
        "Check status or get full output of a background task. "
        "Returns status, exit code, stdout, and stderr. "
        "You will be automatically notified when background tasks complete, "
        "then use this tool to retrieve the full output."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Background task ID (e.g., 'bg-1')",
            },
        },
        "required": ["task_id"],
    },
)

BACKGROUND_TOOLS = [
    CHECK_BACKGROUND_TASK_TOOL,
]

# ClarAIty Knowledge & Task Tools

CLARAITY_SCAN_FILES_TOOL = ToolDefinition(
    name="claraity_scan_files",
    description="Auto-discover source files and add as layer 4 nodes. Language-agnostic. Run as first step when building knowledge for a new repo.",
    parameters={
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "Root directory to scan (default: 'src')"},
            "extensions": {"type": "string", "description": "Comma-separated extensions (default: .py,.ts,.tsx,.js,.jsx,.go,.java,.rs)"},
        },
        "required": [],
    },
)

CLARAITY_ADD_NODE_TOOL = ToolDefinition(
    name="claraity_add_node",
    description="Add a node to the knowledge graph: system (L1), module (L2), component (L3), decision, invariant, or flow (L0).",
    parameters={
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "Unique ID. Convention: sys-<name>, mod-<name>, comp-<name>, dec-<name>, inv-<name>, flow-<name>"},
            "node_type": {"type": "string", "enum": ["system", "module", "component", "decision", "invariant", "flow"], "description": "Node type"},
            "name": {"type": "string", "description": "Human-readable name"},
            "description": {"type": "string", "description": "What this entity does"},
            "layer": {"type": "integer", "description": "Zoom level: 0=cross-cutting, 1=system, 2=module, 3=component"},
            "file_path": {"type": "string", "description": "Source file path"},
            "line_count": {"type": "integer", "description": "Lines of code"},
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "properties": {"type": "string", "description": "JSON string of additional properties"},
        },
        "required": ["node_id", "node_type", "name"],
    },
)

CLARAITY_ADD_EDGE_TOOL = ToolDefinition(
    name="claraity_add_edge",
    description="Add a relationship edge between two nodes. Types: uses, calls, contains, writes, reads, emits, constrains, dispatches, renders, spawns, controls, bridges.",
    parameters={
        "type": "object",
        "properties": {
            "from_id": {"type": "string", "description": "Source node ID"},
            "to_id": {"type": "string", "description": "Target node ID"},
            "edge_type": {"type": "string", "description": "Relationship type"},
            "label": {"type": "string", "description": "Description of the relationship"},
        },
        "required": ["from_id", "to_id", "edge_type"],
    },
)

CLARAITY_REMOVE_NODE_TOOL = ToolDefinition(
    name="claraity_remove_node",
    description="Remove a node and all connected edges from the knowledge graph. Use for corrections.",
    parameters={
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "ID of the node to remove"},
        },
        "required": ["node_id"],
    },
)

CLARAITY_BRIEF_TOOL = ToolDefinition(
    name="claraity_brief",
    description="Get a compact architecture overview of the codebase: modules, dependencies, design decisions, and invariants. Use at session start or when you need to understand the overall structure.",
    parameters={"type": "object", "properties": {}, "required": []},
)

CLARAITY_MODULE_TOOL = ToolDefinition(
    name="claraity_module",
    description="Get detailed information about a module: its components, files, dependencies, and relationships. Use when you need to understand or modify a specific module.",
    parameters={
        "type": "object",
        "properties": {
            "module_id": {
                "type": "string",
                "description": "Module ID (e.g., mod-core, mod-memory, mod-ui, mod-tools, mod-llm, mod-server)",
            },
        },
        "required": ["module_id"],
    },
)

CLARAITY_FILE_TOOL = ToolDefinition(
    name="claraity_file",
    description="Get a file's role, parent module, component it defines, dependencies, and applicable design decisions. Use BEFORE reading a file to understand its context.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "File path relative to project root (e.g., src/core/agent.py)",
            },
        },
        "required": ["file_path"],
    },
)

CLARAITY_SEARCH_TOOL = ToolDefinition(
    name="claraity_search",
    description="Search the codebase knowledge base by keyword. Returns matching components, modules, files, decisions, and their relationships.",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Search keyword (e.g., 'memory', 'auth', 'streaming')",
            },
        },
        "required": ["keyword"],
    },
)

CLARAITY_IMPACT_TOOL = ToolDefinition(
    name="claraity_impact",
    description="Show what would be affected by changing a component. Returns direct and indirect dependents (blast radius). Use BEFORE modifying a component to understand risk.",
    parameters={
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Component ID (e.g., comp-coding-agent, comp-memory-mgr, comp-message-store)",
            },
        },
        "required": ["component_id"],
    },
)

TASK_LIST_TOOL = ToolDefinition(
    name="task_list",
    description="Get tasks that are unblocked and ready to start, sorted by priority. Use to find what to work on next.",
    parameters={"type": "object", "properties": {}, "required": []},
)

TASK_CREATE_TOOL = ToolDefinition(
    name="task_create",
    description="Create a new task with title, description, priority, and optional tags.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title"},
            "description": {"type": "string", "description": "Task description"},
            "priority": {"type": "integer", "description": "Priority (0=highest, 5=default)"},
            "parent_id": {"type": "string", "description": "Parent task ID for subtasks"},
            "tags": {"type": "string", "description": "Comma-separated tags"},
        },
        "required": ["title"],
    },
)

TASK_UPDATE_TOOL = ToolDefinition(
    name="task_update",
    description="Update a task's status (start/close) or add a note.",
    parameters={
        "type": "object",
        "properties": {
            "bead_id": {"type": "string", "description": "Task ID (e.g., bd-a1b2)"},
            "action": {"type": "string", "enum": ["start", "close", "note"], "description": "Action to take"},
            "summary": {"type": "string", "description": "For close: what was done. For note: content."},
        },
        "required": ["bead_id", "action"],
    },
)

TASK_BLOCK_TOOL = ToolDefinition(
    name="task_block",
    description="Add a blocking dependency: blocker must complete before blocked can start.",
    parameters={
        "type": "object",
        "properties": {
            "blocker_id": {"type": "string", "description": "Task that must complete first"},
            "blocked_id": {"type": "string", "description": "Task that cannot start until blocker completes"},
        },
        "required": ["blocker_id", "blocked_id"],
    },
)

CLARAITY_AUTO_LAYOUT_TOOL = ToolDefinition(
    name="claraity_auto_layout",
    description="Compute flow_rank/flow_col layout for all modules based on dependency graph. Call after populating modules and edges.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

CLARAITY_EXPORT_TOOL = ToolDefinition(
    name="claraity_export",
    description="Export knowledge DB and beads DB to JSONL files for git tracking. Call after finishing modifications to the knowledge base.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

CLARAITY_TOOLS = [
    CLARAITY_SCAN_FILES_TOOL,
    CLARAITY_ADD_NODE_TOOL,
    CLARAITY_ADD_EDGE_TOOL,
    CLARAITY_REMOVE_NODE_TOOL,
    CLARAITY_BRIEF_TOOL,
    CLARAITY_MODULE_TOOL,
    CLARAITY_FILE_TOOL,
    CLARAITY_SEARCH_TOOL,
    CLARAITY_IMPACT_TOOL,
    TASK_LIST_TOOL,
    TASK_CREATE_TOOL,
    TASK_UPDATE_TOOL,
    TASK_BLOCK_TOOL,
    CLARAITY_AUTO_LAYOUT_TOOL,
    CLARAITY_EXPORT_TOOL,
]


# Tool Collections

ALL_TOOLS = [
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    APPEND_TO_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    RUN_COMMAND_TOOL,
    GREP_TOOL,
    GLOB_TOOL,
    GET_FILE_OUTLINE_TOOL,
    GET_SYMBOL_CONTEXT_TOOL,
    DELEGATE_TO_SUBAGENT_TOOL,
    # Task tools (task_create/task_update/task_list/task_block) are backed by BeadStore
    # and registered dynamically via tool_executor, not listed here
    CREATE_CHECKPOINT_TOOL,
    RUN_TESTS_TOOL,
    DETECT_TEST_FRAMEWORK_TOOL,
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    CLARIFY_TOOL,
    ENTER_PLAN_MODE_TOOL,
    EXIT_PLAN_MODE_TOOL,
    DIRECTOR_COMPLETE_UNDERSTAND_TOOL,
    DIRECTOR_COMPLETE_PLAN_TOOL,
    DIRECTOR_COMPLETE_SLICE_TOOL,
    DIRECTOR_COMPLETE_INTEGRATION_TOOL,
    # ClarAIty Knowledge & Task tools
    *CLARAITY_TOOLS,
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
    GREP_TOOL,
    GLOB_TOOL,
    GET_FILE_OUTLINE_TOOL,
    GET_SYMBOL_CONTEXT_TOOL,
]

EXECUTION_TOOLS = [
    RUN_COMMAND_TOOL,
]

TESTING_TOOLS = [
    RUN_TESTS_TOOL,
    DETECT_TEST_FRAMEWORK_TOOL,
]


def get_tools_for_task(task_type: str) -> list[ToolDefinition]:
    """
    Get relevant tools based on task type.

    Args:
        task_type: Type of task (feature, bug_fix, refactor, etc.)

    Returns:
        list of relevant tool definitions
    """
    # For most tasks, return all tools
    # Can be refined later based on task analysis
    return ALL_TOOLS


def get_all_tools(
    mcp_definitions: list[ToolDefinition] | None = None,
) -> list[ToolDefinition]:
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
    "DELEGATE_TO_SUBAGENT_TOOL",
    "CREATE_CHECKPOINT_TOOL",
    "ALL_TOOLS",
    "FILE_TOOLS",
    "CODE_TOOLS",
    "EXECUTION_TOOLS",
    "CLARIFY_TOOL",
    "ENTER_PLAN_MODE_TOOL",
    "EXIT_PLAN_MODE_TOOL",
    "PLAN_MODE_TOOLS",
    "get_tools_for_task",
    "get_all_tools",
]
