"""
Rich UX formatting for streaming tool call output.

This module provides professional formatting for tool calls during streaming,
matching modern coding agent UX standards (Claude Code, Cursor, etc.).
"""

import difflib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ToolOutputFormatter:
    """
    Formats tool call output for professional streaming UX.

    Features:
    - Syntax highlighting for code files
    - Formatted TODO checklists
    - Clean tool announcements
    - Diff display for file edits
    """

    def __init__(self):
        """Initialize formatter with syntax highlighting support."""
        # Enable Windows ANSI support (critical for PowerShell/cmd)
        self._enable_windows_ansi()

        self.syntax_highlighter = None
        self.is_terminal = self._is_terminal()
        self._init_syntax_highlighter()

    def _enable_windows_ansi(self):
        """
        Enable ANSI escape sequence support on Windows.

        Windows 10+ supports ANSI codes, but Virtual Terminal Processing
        must be enabled. This is what Claude Code does to get colors working
        in PowerShell and cmd.exe.
        """
        if sys.platform != "win32":
            return  # Only needed on Windows

        try:
            # Try using colorama (easiest cross-platform solution)
            import colorama

            colorama.init()
            logger.debug("ANSI support enabled via colorama")
        except ImportError:
            # Colorama not available, try Windows API directly
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32

                # Get stdout handle
                stdout_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE

                # Enable Virtual Terminal Processing (0x0004)
                # Also enable processed output (0x0001) and wrap at EOL (0x0002)
                mode = ctypes.c_uint32()
                kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode))
                mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(stdout_handle, mode)

                logger.debug("ANSI support enabled via Windows API")
            except Exception as e:
                logger.warning(f"Failed to enable Windows ANSI support: {e}")
                # Continue anyway - might still work in Windows Terminal

    def _is_terminal(self) -> bool:
        """
        Check if stdout is a terminal (TTY).

        Returns:
            True if stdout is a terminal, False otherwise
        """
        try:
            return sys.stdout.isatty()
        except AttributeError:
            # stdout doesn't have isatty (e.g., in some test environments)
            return False

    def _init_syntax_highlighter(self):
        """Initialize Pygments syntax highlighter if available."""
        try:
            from pygments import highlight
            from pygments.formatters import TerminalFormatter
            from pygments.lexers import get_lexer_by_name, guess_lexer
            from pygments.util import ClassNotFound

            self.syntax_highlighter = {
                "highlight": highlight,
                "get_lexer_by_name": get_lexer_by_name,
                "guess_lexer": guess_lexer,
                "TerminalFormatter": TerminalFormatter,
                "ClassNotFound": ClassNotFound,
            }
        except ImportError:
            # Pygments not available - will fall back to plain text
            self.syntax_highlighter = None

    def _validate_file_path(self, file_path: str) -> bool:
        """
        Validate file path is safe (no path traversal, null bytes).

        Args:
            file_path: Path to validate

        Returns:
            True if path is safe, False otherwise
        """
        if not file_path:
            return False

        # Check for path traversal attempts
        if ".." in file_path:
            logger.warning(f"Rejected suspicious file path with '..' traversal: {file_path}")
            return False

        # Check for null bytes
        if "\x00" in file_path:
            logger.warning(f"Rejected file path with null byte: {file_path}")
            return False

        # Check for absolute paths (should be relative)
        try:
            path = Path(file_path)
            if path.is_absolute():
                logger.warning(f"Rejected absolute file path: {file_path}")
                return False
            return True
        except (ValueError, OSError) as e:
            logger.warning(f"Invalid file path: {file_path} - {e}")
            return False

    def _sanitize_content(self, content: str, max_bytes: int = 1_000_000) -> str | None:
        """
        Sanitize content before syntax highlighting.

        Args:
            content: Content to sanitize
            max_bytes: Maximum size in bytes

        Returns:
            Sanitized content, or None if content is invalid
        """
        # Check if content is string
        if not isinstance(content, str):
            logger.warning(f"Content is not a string: {type(content)}")
            return None

        # Check size to prevent DoS
        if len(content) > max_bytes:
            logger.warning(f"Content too large for highlighting: {len(content)} bytes")
            truncated = content[:max_bytes]
            truncated += f"\n... (truncated {len(content) - max_bytes} bytes for safety)"
            return truncated

        # Try to validate it's text (not binary)
        try:
            # Attempt to encode/decode to catch encoding issues
            content.encode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError, AttributeError) as e:
            logger.warning(f"Binary or invalid UTF-8 content detected: {e}")
            return None

        return content

    def _is_binary_file(self, file_path: str) -> bool:
        """
        Check if file is a known binary type.

        Args:
            file_path: File path to check

        Returns:
            True if binary file extension
        """
        binary_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".svg",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".dat",
            ".db",
            ".sqlite",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".7z",
            ".rar",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".wav",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
        }

        ext = Path(file_path).suffix.lower()
        return ext in binary_extensions

    def format_tool_announcement(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Format the initial tool call announcement.

        Args:
            tool_name: Name of the tool being called
            arguments: Tool arguments (may be incomplete during streaming)

        Returns:
            Formatted announcement string
        """
        # Map tool names to clean icons/emojis
        # Using safe symbols that work on Windows
        tool_icons = {
            "write_file": "[WRITE]",
            "edit_file": "[EDIT]",
            "read_file": "[READ]",
            "append_to_file": "[APPEND]",
            "list_directory": "[LIST]",
            "search_code": "[SEARCH]",
            "analyze_code": "[ANALYZE]",
            "run_command": "[RUN]",
            "todo_write": "[TODO]",
            "git_status": "[GIT]",
            "git_diff": "[DIFF]",
        }

        icon = tool_icons.get(tool_name, "[CALL]")

        # Extract key parameter for display
        if tool_name in ["write_file", "edit_file", "read_file", "append_to_file", "analyze_code"]:
            file_path = arguments.get("file_path", "")
            if file_path and self._validate_file_path(file_path):
                return f"\n{icon} {Path(file_path).name}\n"

        elif tool_name == "run_command":
            command = arguments.get("command", "")
            if command:
                # Truncate long commands
                if len(command) > 50:
                    command = command[:50] + "..."
                return f"\n{icon} {command}\n"

        elif tool_name == "search_code":
            query = arguments.get("query", "")
            if query:
                if len(query) > 50:
                    query = query[:50] + "..."
                return f"\n{icon} {query}\n"

        elif tool_name == "todo_write":
            return f"\n{icon} Updating task list\n"

        # Default: Just show tool name
        return f"\n{icon} {tool_name}\n"

    def format_file_content(self, file_path: str, content: str, max_lines: int = 100) -> str:
        """
        Format file content with syntax highlighting.

        Args:
            file_path: Path to file (for language detection)
            content: File content
            max_lines: Maximum lines to display (prevent flooding)

        Returns:
            Formatted content (syntax highlighted if available)
        """
        # Validate file path
        if not self._validate_file_path(file_path):
            logger.error(f"Invalid file path rejected: {file_path}")
            return "[Error: Invalid file path]"

        # Check for binary files
        if self._is_binary_file(file_path):
            return "[Binary file - content not displayed]"

        # Sanitize content
        sanitized = self._sanitize_content(content)
        if sanitized is None:
            return "[Binary or invalid content - not displayed]"

        content = sanitized

        # Truncate if too long (do this AFTER sanitization to handle size limits)
        lines = content.split("\n")
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines])
            content += f"\n... ({len(lines) - max_lines} more lines)\n"

        # Try syntax highlighting in terminal contexts
        # (We've enabled Windows ANSI support, so this should work on all platforms)
        if self.syntax_highlighter and self.is_terminal:
            try:
                # Get file extension to determine language
                ext = Path(file_path).suffix.lower()
                lang_map = {
                    ".py": "python",
                    ".js": "javascript",
                    ".ts": "typescript",
                    ".jsx": "jsx",
                    ".tsx": "tsx",
                    ".java": "java",
                    ".cpp": "cpp",
                    ".c": "c",
                    ".go": "go",
                    ".rs": "rust",
                    ".rb": "ruby",
                    ".php": "php",
                    ".html": "html",
                    ".css": "css",
                    ".sql": "sql",
                    ".sh": "bash",
                    ".yaml": "yaml",
                    ".yml": "yaml",
                    ".json": "json",
                    ".xml": "xml",
                    ".md": "markdown",
                }

                language = lang_map.get(ext)

                if language:
                    lexer = self.syntax_highlighter["get_lexer_by_name"](language)
                    formatter = self.syntax_highlighter["TerminalFormatter"]()
                    highlighted = self.syntax_highlighter["highlight"](content, lexer, formatter)
                    return highlighted.rstrip()

            except self.syntax_highlighter["ClassNotFound"]:
                # Expected: Unknown language
                logger.debug(f"No lexer found for {ext}, using plain text")
            except Exception as e:
                # Unexpected error - log it but continue
                logger.error(f"Syntax highlighting failed for {file_path}: {type(e).__name__}: {e}")

        # No syntax highlighting or not a terminal - return plain text
        if not self.is_terminal and self.syntax_highlighter:
            logger.debug("Syntax highlighting disabled - not a terminal (stdout.isatty() = False)")

        return content

    def format_todo_list(self, todos: list) -> str:
        """
        Format TODO list for clean display.

        Args:
            todos: list of todo items with content, status, activeForm

        Returns:
            Formatted checklist
        """
        # Safe symbols for Windows
        status_symbols = {"pending": "[ ]", "in_progress": "[>]", "completed": "[X]"}

        lines = []
        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            active_form = todo.get("activeForm", content)

            symbol = status_symbols.get(status, "[ ]")

            # Use activeForm for in_progress, content for others
            text = active_form if status == "in_progress" else content

            lines.append(f"  {symbol} {text}")

        return "\n".join(lines)

    def format_diff(self, old_text: str, new_text: str, max_context: int = 5) -> str:
        """
        Format a simple diff view for file edits.

        Args:
            old_text: Original text
            new_text: New text
            max_context: Maximum context lines to show

        Returns:
            Formatted diff (simple +/- format)
        """
        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")

        # Simple diff: show removed and added lines
        lines = []
        lines.append("Changes:")

        # Show removed lines (limited)
        if len(old_lines) <= max_context:
            for line in old_lines:
                lines.append(f"  - {line}")
        else:
            lines.append(f"  - ... ({len(old_lines)} lines removed)")

        # Show added lines (limited)
        if len(new_lines) <= max_context:
            for line in new_lines:
                lines.append(f"  + {line}")
        else:
            lines.append(f"  + ... ({len(new_lines)} lines added)")

        return "\n".join(lines)

    def format_file_operation_diff(
        self,
        file_path: str,
        new_content: str,
        old_content: str | None = None,
        max_lines: int = 1000,
    ) -> str:
        """
        Format file operations as unified diff with line numbers (Claude Code style).

        For new files (write_file): Shows all lines as additions with line numbers
        For edits (edit_file): Shows unified diff with context, deletions, and additions

        Args:
            file_path: Path to the file
            new_content: New file content
            old_content: Original content (None for new files)
            max_lines: Maximum lines to display

        Returns:
            Formatted diff output with line numbers, colors, and indentation
        """
        # Validate inputs
        if not self._validate_file_path(file_path):
            return "  [Error: Invalid file path]"

        # Check for binary files
        if self._is_binary_file(file_path):
            return "  [Binary file - content not displayed]"

        # Sanitize content
        new_content = self._sanitize_content(new_content) or ""
        if old_content:
            old_content = self._sanitize_content(old_content) or ""

        # Split into lines
        new_lines = new_content.splitlines()
        old_lines = old_content.splitlines() if old_content else []

        # Check if too many lines
        total_lines = len(new_lines)
        if total_lines > max_lines:
            new_lines = new_lines[:max_lines]
            truncated = True
        else:
            truncated = False

        output_lines = []

        if old_content is None:
            # NEW FILE - Show all lines as additions
            for i, line in enumerate(new_lines, start=1):
                formatted_line = self._format_diff_line(i, "+", line)
                output_lines.append(formatted_line)

            if truncated:
                output_lines.append(f"  ... ({total_lines - max_lines} more lines)")

        else:
            # EDIT FILE - Show unified diff
            output_lines = self._generate_unified_diff_with_line_numbers(
                old_lines, new_lines, max_lines
            )

        return "\n".join(output_lines)

    def _format_diff_line(self, line_num: int, prefix: str, content: str) -> str:
        """
        Format a single diff line with line number, prefix, and background color.

        Uses git diff style with background colors (green for additions, red for deletions).

        Args:
            line_num: Line number
            prefix: '+' for addition, '-' for deletion, ' ' for context
            content: Line content

        Returns:
            Formatted line with ANSI background colors (if terminal)
        """
        # Format line number (right-aligned, 4 chars wide)
        line_num_str = f"{line_num:4}"

        # Add colors if in terminal
        if self.is_terminal:
            if prefix == "+":
                # Dark green background for additions (professional style)
                # \x1b[48;5;22m = dark green background
                # \x1b[38;5;158m = light green text for good contrast
                return f"  \x1b[48;5;22m\x1b[38;5;158m{line_num_str} {prefix} {content}\x1b[0m"
            elif prefix == "-":
                # Dark red background for deletions (professional style)
                # \x1b[48;5;52m = dark red background
                # \x1b[38;5;217m = light pink/red text for good contrast
                return f"  \x1b[48;5;52m\x1b[38;5;217m{line_num_str} {prefix} {content}\x1b[0m"
            else:
                # No color for context
                return f"  {line_num_str}   {content}"
        else:
            # Plain text (no colors)
            return f"  {line_num_str} {prefix} {content}"

    def _generate_unified_diff_with_line_numbers(
        self, old_lines: list[str], new_lines: list[str], max_lines: int
    ) -> list[str]:
        """
        Generate unified diff with line numbers using difflib.

        Args:
            old_lines: Original file lines
            new_lines: New file lines
            max_lines: Maximum lines to display

        Returns:
            list of formatted diff lines
        """
        # Generate unified diff using difflib
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm="",
            n=3,  # 3 lines of context
        )

        output_lines = []
        old_line_num = 0
        new_line_num = 0
        lines_shown = 0

        for line in diff:
            # Skip header lines (@@, ---, +++)
            if line.startswith("@@"):
                # Parse line numbers from header
                # Format: @@ -old_start,old_count +new_start,new_count @@
                parts = line.split()
                if len(parts) >= 3:
                    old_info = parts[1]  # -old_start,old_count
                    new_info = parts[2]  # +new_start,new_count

                    # Extract start line numbers
                    if "," in old_info:
                        old_line_num = int(old_info.split(",")[0][1:])  # Remove '-'
                    else:
                        old_line_num = int(old_info[1:])

                    if "," in new_info:
                        new_line_num = int(new_info.split(",")[0][1:])  # Remove '+'
                    else:
                        new_line_num = int(new_info[1:])

                continue

            if line.startswith("---") or line.startswith("+++"):
                continue

            # Check max lines limit
            if lines_shown >= max_lines:
                output_lines.append(f"  ... (diff truncated at {max_lines} lines)")
                break

            # Process diff line
            if line.startswith("+"):
                # Addition
                formatted = self._format_diff_line(new_line_num, "+", line[1:])
                output_lines.append(formatted)
                new_line_num += 1
                lines_shown += 1

            elif line.startswith("-"):
                # Deletion
                formatted = self._format_diff_line(old_line_num, "-", line[1:])
                output_lines.append(formatted)
                old_line_num += 1
                lines_shown += 1

            else:
                # Context line (starts with ' ')
                content = line[1:] if line.startswith(" ") else line
                formatted = self._format_diff_line(new_line_num, " ", content)
                output_lines.append(formatted)
                old_line_num += 1
                new_line_num += 1
                lines_shown += 1

        return output_lines


class StreamingToolCallFormatter:
    """
    Handles formatting of tool calls as they stream in.

    This accumulates tool arguments as they arrive in chunks,
    then formats and displays them once complete.
    """

    def __init__(self):
        """Initialize streaming formatter."""
        self.formatter = ToolOutputFormatter()
        self.accumulator: dict[str, Any] = {}
        self.announced = False

    def reset(self):
        """Reset for a new tool call."""
        self.accumulator = {}
        self.announced = False

    def should_announce(self, tool_name: str) -> bool:
        """Check if we should announce this tool call."""
        if not self.announced:
            self.announced = True
            return True
        return False

    def accumulate_arguments(self, args_chunk: str):
        """
        Accumulate argument chunks as they stream.

        Args:
            args_chunk: Chunk of JSON arguments
        """
        if "raw_json" not in self.accumulator:
            self.accumulator["raw_json"] = ""

        self.accumulator["raw_json"] += args_chunk

    def format_complete_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """
        Format a complete tool call for display.

        Args:
            tool_name: Name of the tool
            arguments: Complete parsed arguments

        Returns:
            Formatted output (None if should skip formatting)
        """
        # Handle specific tool types

        if tool_name == "write_file":
            file_path = arguments.get("file_path", "")
            content = arguments.get("content", "")

            if file_path and content:
                formatted_content = self.formatter.format_file_content(file_path, content)
                return f"\n{formatted_content}\n"

        elif tool_name == "edit_file":
            file_path = arguments.get("file_path", "")
            old_text = arguments.get("old_text", "")
            new_text = arguments.get("new_text", "")

            if file_path:
                diff = self.formatter.format_diff(old_text, new_text)
                return f"\n{diff}\n"

        elif tool_name == "todo_write":
            todos = arguments.get("todos", [])
            if todos:
                formatted_todos = self.formatter.format_todo_list(todos)
                return f"\n{formatted_todos}\n"

        elif tool_name == "read_file":
            # Don't display file content for read operations
            # (the tool result will show it)
            return None

        elif tool_name in ["search_code", "analyze_code", "list_directory"]:
            # Don't display for query tools
            # (the tool result will show findings)
            return None

        # For other tools, no special formatting needed
        return None


def format_tool_call(tool_name: str, arguments: dict[str, Any]) -> str:
    """
    Quick helper to format a tool call announcement.

    Args:
        tool_name: Name of the tool
        arguments: Tool arguments

    Returns:
        Formatted announcement
    """
    formatter = ToolOutputFormatter()
    return formatter.format_tool_announcement(tool_name, arguments)
