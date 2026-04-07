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
    description=(
        "Read file contents with line-range support. Returns content with line numbers (cat -n format). "
        "Reads up to 1000 lines by default (max 2000 per call).\n\n"
        "THIS IS YOUR PRIMARY TOOL for understanding any file. "
        "You MUST read a file before making claims about it or editing it. "
        "Do NOT use run_command with cat/head/tail to read files -- use this tool instead.\n\n"
        "For large files, use start_line/end_line to read specific sections rather than "
        "reading the whole file. If you don't know where to look, read the first chunk to "
        "orient, then target subsequent reads.\n"
        "If file is already in <referenced_files> context, do NOT re-read it."
    ),
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
    description=(
        "Create a new file or completely rewrite an existing file. "
        "Prefer edit_file for modifying existing files -- it only sends the diff.\n\n"
        "Rules:\n"
        "- Do NOT create documentation files (*.md, README) unless explicitly requested\n"
        "- Do NOT use run_command with echo/cat heredoc to write files -- use this tool\n"
        "- ALWAYS prefer editing existing files over creating new ones (prevents file bloat)\n"
        "- Keep files under 100 lines if possible -- break large files into skeleton + edits"
    ),
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
    description=(
        "Edit an existing file by replacing specific text. The old_text must match exactly "
        "including whitespace and indentation.\n\n"
        "Rules:\n"
        "- You MUST read the file first before editing. This tool will fail if you haven't.\n"
        "- Do NOT use run_command with sed/awk/perl to edit files -- use this tool\n"
        "- Preserve exact indentation from the file (tabs/spaces as they appear)\n"
        "- If old_text is not unique, provide more surrounding context to disambiguate\n"
        "- Only edit code you need to change. Do not add docstrings, comments, or type "
        "annotations to surrounding code you didn't modify"
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "old_text": {
                "type": "string",
                "description": "Exact text to find and replace. Must match exactly including whitespace. Must be unique in the file -- if multiple matches exist, the edit will fail. Provide more surrounding context to disambiguate.",
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
    description=(
        "List all files and subdirectories in a directory. "
        "Use this instead of run_command with ls/dir/Get-ChildItem. "
        "For finding files by pattern across directories, use glob instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "directory_path": {"type": "string", "description": "Path to the directory to list"}
        },
        "required": ["directory_path"],
    },
)

def _build_run_command_description() -> str:
    """Build run_command description dynamically based on detected shell.

    Modeled after Claude Code's Bash tool description — co-locates all behavioral
    guidance with the tool definition so the LLM sees it at call time.
    """
    from src.platform import detect_preferred_shell

    shell_info = detect_preferred_shell()

    base = (
        "Execute a shell command and return its output. "
        "Use for running tests, building projects, executing scripts, package management, and git operations.\n\n"
    )

    # --- Shell environment (platform-adaptive) ---
    if shell_info["syntax"] == "unix":
        shell_section = (
            "IMPORTANT - Shell environment:\n"
            f"- Commands run in {shell_info['shell']} (Unix syntax).\n"
            "- Use '&&' to chain dependent commands, '; ' for independent ones.\n"
            "- Standard Unix tools available: grep, sed, awk, tail, head, etc.\n"
        )
    else:
        shell_section = (
            "IMPORTANT - Shell environment:\n"
            "- Commands run in PowerShell 5.1 (NOT cmd.exe, NOT bash).\n"
            "- Do NOT use '&&' to chain commands -- use '; ' (semicolon) instead.\n"
            "- Do NOT use 'cd /d' (cmd.exe syntax). Use 'Set-Location' or 'cd'.\n"
        )

    # --- Dedicated tool preference (specific tool names) ---
    dont_use = (
        "\nDo NOT use run_command for these -- use dedicated tools instead:\n"
        "- Reading files: cat, head, tail, type -> use read_file\n"
        "- Searching content: grep, rg, findstr, Select-String -> use grep tool\n"
        "- Finding files: find, ls, dir, Get-ChildItem -> use glob or list_directory\n"
        "- Editing files: sed, awk, perl -i -> use edit_file\n"
        "- Writing files: echo >>, cat <<EOF -> use write_file\n"
        "Using dedicated tools gives better auditability and user experience.\n"
    )

    # --- Working directory & paths ---
    paths = (
        "\nWorking directory:\n"
        "- Prefer the working_directory parameter over 'cd' commands.\n"
        "- Use absolute paths to avoid losing your place between calls.\n"
        "- Always quote file paths that contain spaces with double quotes.\n"
    )

    # --- Multiple commands ---
    multi_cmd = (
        "\nMultiple commands:\n"
        "- Independent commands that can run in parallel -> make separate run_command calls.\n"
        "- Dependent commands that must run sequentially -> chain with '&&'.\n"
        "- Do NOT use newlines to separate commands in a single call.\n"
    )

    # --- Background execution ---
    background = (
        "\nLong-running commands:\n"
        "- Use background=true for commands that take >30s (test suites, builds, linters).\n"
        "- You will be notified when the background task completes -- do NOT poll or sleep.\n"
        "- Do not use '&' at the end of the command; use the background parameter instead.\n"
    )

    # --- Behavioral guardrails ---
    guardrails = (
        "\nBehavioral rules:\n"
        "- Always provide the description parameter (e.g., 'Run unit tests', 'Install dependencies').\n"
        "- Commands run non-interactively (no terminal input). Do NOT run commands that require "
        "interactive input (ssh without key auth, docker login, interactive installers).\n"
        "- Avoid unnecessary 'sleep' commands. Do not sleep between commands that can run immediately.\n"
        "- Do not retry the identical failing command blindly. Diagnose the error first, then try a targeted fix.\n"
        "- If a command fails, read the error message and check your assumptions before switching approach.\n"
        "- After a failure, try at most 3 attempts with the same approach before switching tactics.\n"
    )

    # --- Git safety ---
    git_safety = (
        "\nGit safety:\n"
        "- Never run destructive git commands (push --force, reset --hard, checkout ., clean -f, branch -D) "
        "without explicit user request.\n"
        "- Never update git config.\n"
        "- Never skip hooks (--no-verify) unless the user explicitly asks.\n"
        "- Never use -i flag (git rebase -i, git add -i) -- interactive input not supported.\n"
        "- Prefer creating new commits over amending existing ones.\n"
        "- When staging files, prefer specific file names over 'git add -A' or 'git add .'.\n"
        "- Use HEREDOC for multi-line commit messages:\n"
        '  git commit -m "$(cat <<\'EOF\'\\nMessage\\n\\nCo-Authored-By: AI Coding Agent <agent@example.com>\\nEOF\\n)"\n'
    )

    return base + shell_section + dont_use + paths + multi_cmd + background + guardrails + git_safety


RUN_COMMAND_TOOL = ToolDefinition(
    name="run_command",
    description=_build_run_command_description(),
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
                    "DO NOT call check_background_task after launching — you will automatically receive "
                    "a [BACKGROUND TASK UPDATE] notification with the full output when the task completes. "
                    "Use for long-running operations like test suites, builds, or linters "
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
    description=(
        "Advanced regex search across files with file type filters, context lines, and "
        "multiple output modes. Use for finding code patterns, error handling, TODOs, etc.\n\n"
        "Use this instead of run_command with grep/rg/findstr/Select-String.\n"
        "Uses Python regex (re module), not shell grep. Use '|' for alternation (not '\\|'). "
        "Examples: 'Key|key', 'log.*Error', 'function\\s+\\w+'. "
        "For cross-line patterns, enable multiline mode."
    ),
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
    description=(
        "Fast file pattern matching with recursive search. Find files by glob patterns "
        "(e.g., **/*.py, src/**/*.{ts,tsx}). Returns sorted by modification time.\n\n"
        "Use this instead of run_command with find/ls/dir/Get-ChildItem to locate files."
    ),
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

# Delegation Tool

DELEGATE_TO_SUBAGENT_TOOL = ToolDefinition(
    name="delegate_to_subagent",
    description=(
        "Delegate a task to a specialized subagent for focused execution. Subagents have "
        "independent context (no pollution of main conversation). "
        "Available: code-writer, code-reviewer, test-writer, doc-writer, explore, planner, general-purpose.\n\n"
        "Proactively delegate to code-reviewer after: changes touching 3+ files, async/concurrency code, "
        "auth/security code, agent control loop or persistence changes.\n"
        "Proactively delegate to test-writer after: new features, bug fixes, refactoring critical paths."
    ),
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


# Web Tools

WEB_SEARCH_TOOL = ToolDefinition(
    name="web_search",
    description=(
        "Search the web for current information. Returns results with citations. "
        "Use for: documentation, error messages, library versions, best practices. "
        "Don't search for fundamental concepts you already know or repeat the same query in a session. "
        "Always cite sources in your response."
    ),
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
    description=(
        "Ask the user clarifying questions before proceeding with ambiguous tasks. "
        "Use when the task has multiple valid approaches and user preference matters. "
        "Do NOT use when: user gave explicit instructions, only one reasonable approach exists, "
        "or codebase conventions make the choice obvious. Max 4 focused questions."
    ),
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
                            "description": "Unique identifier AND display label for this question (e.g., 'approach', 'framework'). Used as the tab label and response key.",
                        },
                        "question": {
                            "type": "string",
                            "description": "The full question text to display",
                        },
                        "options": {
                            "type": "array",
                            "minItems": 1,
                            "description": "Available answer options. Omit for free-text questions.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Unique identifier AND display label for this option (e.g., 'TypeScript', 'Full feature'). Used as the response value.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Optional longer description shown below the option label",
                                    },
                                    "recommended": {
                                        "type": "boolean",
                                        "description": "Mark this option as recommended",
                                    },
                                },
                                "required": ["id"],
                            },
                        },
                        "multi_select": {
                            "type": "boolean",
                            "description": "Allow multiple options to be selected (default: false)",
                        },
                    },
                    "required": ["id", "question"],
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
        "at .claraity/plans/director_plan.md. Then call this tool with the file path "
        "and a list of slice titles for execution tracking."
    ),
    parameters={
        "type": "object",
        "properties": {
            "plan_document": {
                "type": "string",
                "description": "Path to the markdown plan file you wrote (e.g. .claraity/plans/director_plan.md)",
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

KNOWLEDGE_SCAN_FILES_TOOL = ToolDefinition(
    name="knowledge_scan_files",
    description="Auto-discover source files and add as layer 4 nodes. Language-agnostic. Run as first step when building a Knowledge DB for a new repo.",
    parameters={
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "Root directory to scan (default: 'src')"},
            "extensions": {"type": "string", "description": "Comma-separated extensions (default: .py,.ts,.tsx,.js,.jsx,.go,.java,.rs)"},
        },
        "required": [],
    },
)

KNOWLEDGE_UPDATE_TOOL = ToolDefinition(
    name="knowledge_update",
    description=(
        "Execute multiple knowledge DB write operations in one call. "
        "Accepts a JSON array of operations (add_node, update_node, add_edge, remove_node, remove_edge). "
        "All operations run in a single DB transaction.\n\n"
        "When to update: at natural milestones (task complete, feature done, session end). "
        "Do NOT update after every individual file edit -- batch changes for efficiency."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Human-readable summary of what this batch does "
                    "(e.g., 'Add mod-core module with 5 components and dependency edges'). "
                    "Shown in the UI tool card for quick understanding."
                ),
            },
            "operations": {
                "type": "string",
                "description": (
                    'JSON array of operations. Each object needs an "op" field. '
                    "Ops: add_node (node_id, node_type, name, layer, description, file_path, line_count, risk_level, properties), "
                    "update_node (node_id, description, risk_level, line_count, properties), "
                    "add_edge (from_id, to_id, edge_type, label, weight), "
                    "remove_node (node_id), "
                    "remove_edge (from_id, to_id, edge_type)"
                ),
            },
        },
        "required": ["summary", "operations"],
    },
)

KNOWLEDGE_QUERY_TOOL = ToolDefinition(
    name="knowledge_query",
    description=(
        "Unified knowledge DB query. All params optional -- combine them. "
        "FTS search (search=), node detail (node_id=), module (module_id=), "
        "file context (file_path=), blast radius (impact=), overview (show='brief').\n\n"
        "Use to ORIENT yourself in unfamiliar areas, check constraints before risky changes, "
        "or find the right file to read. Skip when you already know which file to edit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "FTS5 search: 'streaming', 'async AND NOT test', 'stream*', '\"message store\"'",
            },
            "node_id": {
                "type": "string",
                "description": "Node detail. Comma-separated for multiple: 'comp-memory-manager, comp-message-store'",
            },
            "node_type": {
                "type": "string",
                "description": "Filter: module, component, decision, invariant, flow, file, system",
            },
            "module_id": {"type": "string", "description": "Module detail (e.g., mod-core)"},
            "file_path": {"type": "string", "description": "File context (e.g., src/core/agent.py)"},
            "impact": {"type": "string", "description": "Blast radius for component ID"},
            "related_to": {"type": "string", "description": "Show edges for node ID"},
            "show": {
                "type": "string",
                "description": "Output: detail, brief, overview, metadata, constraints, edges",
            },
            "keyword": {"type": "string", "description": "Simple substring search (prefer search=)"},
        },
        "required": [],
    },
)

KNOWLEDGE_SET_METADATA_TOOL = ToolDefinition(
    name="knowledge_set_metadata",
    description="Store a key-value pair in the knowledge DB metadata (architecture overview, scan info, repo name).",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Metadata key (architecture_overview, repo_name, repo_language, scanned_by, total_files, total_lines)"},
            "value": {"type": "string", "description": "Metadata value"},
        },
        "required": ["key", "value"],
    },
)

TASK_LIST_TOOL = ToolDefinition(
    name="task_list",
    description="Get tasks that are unblocked and ready to start, sorted by priority. Use to find what to work on next.",
    parameters={"type": "object", "properties": {}, "required": []},
)

TASK_SHOW_TOOL = ToolDefinition(
    name="task_show",
    description="Get full detail for a specific task: description, design, acceptance criteria, notes, dependencies. Use when picking up a task.",
    parameters={
        "type": "object",
        "properties": {
            "bead_id": {"type": "string", "description": "Task ID (e.g., bd-a1b2)"},
        },
        "required": ["bead_id"],
    },
)

TASK_CREATE_TOOL = ToolDefinition(
    name="task_create",
    description=(
        "Create a new task with title, description, priority, type, and optional deps.\n\n"
        "Create tasks for the OVERALL work item, not each sub-step. Use task_update with "
        "action='note' for progress within a task. Always provide a meaningful description. "
        "Use deps to link back to the task you were working on (e.g., 'discovered-from:bd-a1b2')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title"},
            "description": {"type": "string", "description": "Why this issue exists and what needs to be done"},
            "priority": {"type": "integer", "description": "Priority (0=highest, 5=default, 9=lowest)"},
            "parent_id": {"type": "string", "description": "Parent task ID for subtasks"},
            "tags": {"type": "string", "description": "Comma-separated tags"},
            "issue_type": {"type": "string", "enum": ["bug", "feature", "task", "epic", "chore", "decision"]},
            "external_ref": {"type": "string", "description": "External reference (e.g., jira-CC-42)"},
            "design": {"type": "string", "description": "Technical design notes"},
            "acceptance_criteria": {"type": "string", "description": "Definition of done"},
            "estimated_minutes": {"type": "integer", "description": "Effort estimate in minutes"},
            "deps": {"type": "string", "description": "Dependencies: 'type:id,...' (e.g., 'discovered-from:bd-a1b2')"},
        },
        "required": ["title"],
    },
)

TASK_UPDATE_TOOL = ToolDefinition(
    name="task_update",
    description="Update a task's lifecycle: start, close, note, defer, reopen, or claim.",
    parameters={
        "type": "object",
        "properties": {
            "bead_id": {"type": "string", "description": "Task ID (e.g., bd-a1b2)"},
            "action": {"type": "string", "enum": ["start", "close", "note", "defer", "reopen", "claim"]},
            "summary": {"type": "string", "description": "For close: what was done. For note: content."},
            "close_reason": {"type": "string", "description": "For close: why (resolved, wontfix, duplicate)"},
            "defer_until": {"type": "string", "description": "For defer: ISO8601 date to reappear"},
            "claimant": {"type": "string", "description": "For claim: identity of claimer"},
        },
        "required": ["bead_id", "action"],
    },
)

TASK_LINK_TOOL = ToolDefinition(
    name="task_link",
    description="Add a typed dependency between tasks. Default: blocks (from must complete before to can start).",
    parameters={
        "type": "object",
        "properties": {
            "from_id": {"type": "string", "description": "Source task ID"},
            "to_id": {"type": "string", "description": "Target task ID"},
            "dep_type": {"type": "string", "enum": ["blocks", "conditional-blocks", "waits-for", "related", "discovered-from", "caused-by", "tracks", "validates", "supersedes", "duplicates"]},
        },
        "required": ["from_id", "to_id"],
    },
)

# Backward compatibility alias
TASK_BLOCK_TOOL = TASK_LINK_TOOL

KNOWLEDGE_AUTO_LAYOUT_TOOL = ToolDefinition(
    name="knowledge_auto_layout",
    description="Compute flow_rank/flow_col layout for all modules based on dependency graph. Call after populating modules and edges.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

KNOWLEDGE_EXPORT_TOOL = ToolDefinition(
    name="knowledge_export",
    description="Export knowledge DB and beads DB to JSONL files for git tracking. Call at session end or after a batch of knowledge_update operations -- not after every individual update.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

KNOWLEDGE_TOOLS = [
    KNOWLEDGE_SCAN_FILES_TOOL,
    KNOWLEDGE_UPDATE_TOOL,
    KNOWLEDGE_QUERY_TOOL,
    KNOWLEDGE_SET_METADATA_TOOL,
    TASK_LIST_TOOL,
    TASK_SHOW_TOOL,
    TASK_CREATE_TOOL,
    TASK_UPDATE_TOOL,
    TASK_LINK_TOOL,
    KNOWLEDGE_AUTO_LAYOUT_TOOL,
    KNOWLEDGE_EXPORT_TOOL,
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
    DELEGATE_TO_SUBAGENT_TOOL,
    # Task tools (task_create/task_update/task_list/task_block) are backed by BeadStore
    # and registered dynamically via tool_executor, not listed here
    CREATE_CHECKPOINT_TOOL,
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
    *KNOWLEDGE_TOOLS,
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
]

EXECUTION_TOOLS = [
    RUN_COMMAND_TOOL,
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
