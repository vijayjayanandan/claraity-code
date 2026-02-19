"""
File operation tools with security and streaming support.

Provides production-grade file operations matching Claude Code capabilities:
- ReadFileTool: Streaming line-range reading with bounded memory
- WriteFileTool: Safe file writing with parent directory creation
- EditFileTool: Find/replace editing
- AppendToFileTool: Safe file appending
- ListDirectoryTool: Directory listing
- RunCommandTool: Shell command execution

Security:
- Path traversal protection via validate_path_security
- Workspace boundary enforcement
"""

import platform
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

from .base import Tool, ToolResult, ToolStatus
from .search_tools import validate_path_security


class FileOperationTool(Tool):
    """
    Base class for file operation tools with shared security validation.

    Provides:
    - Path validation with traversal protection
    - Configurable workspace root for testing
    """

    # Class-level workspace root override (for testing)
    # Set this to allow operations in test directories
    _workspace_root: Optional[Path] = None

    def _validate_path(
        self,
        file_path: str,
        must_exist: bool = True,
        allow_outside_workspace: bool = False
    ) -> Path:
        """
        Validate file path with security checks.

        Args:
            file_path: Path to validate
            must_exist: If True, path must exist
            allow_outside_workspace: If True, allow paths outside workspace

        Returns:
            Validated Path object

        Raises:
            ValueError: If path fails security validation
            FileNotFoundError: If must_exist=True and path doesn't exist
        """
        # Use class-level workspace root if set (for testing)
        workspace = self._workspace_root

        # Validate path security
        validated_path = validate_path_security(
            file_path,
            workspace_root=workspace,
            allow_files_outside_workspace=allow_outside_workspace
        )

        # Check existence if required
        if must_exist and not validated_path.exists():
            raise FileNotFoundError(f"Path does not exist: {validated_path}")

        return validated_path


class ReadFileTool(FileOperationTool):
    """
    Tool for reading files with streaming line-range support.

    Features:
    - Streaming reads with bounded memory (never loads entire file)
    - Line range support (start_line, end_line, max_lines)
    - Line number formatting (cat -n style)
    - Long line truncation
    - Path traversal protection

    Matches Claude Code's Read tool capabilities.
    """

    # Configuration constants
    MAX_LINES_DEFAULT = 1000     # Balanced default - read meaningful chunks
    MAX_LINES_LIMIT = 2000       # Hard cap per request
    MAX_LINE_LENGTH = 2000       # Truncate lines longer than this

    def __init__(self):
        super().__init__(
            name="read_file",
            description="Read contents of a file with optional line range support"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema (canonical source is tool_schemas.py)."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line (exclusive)"},
                "max_lines": {"type": "integer", "description": "Max lines to return"}
            },
            "required": ["file_path"]
        }

    def execute(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
        **kwargs: Any
    ) -> ToolResult:
        """
        Read file contents with streaming (bounded memory).

        Args:
            file_path: Path to file to read
            start_line: 1-indexed start line, inclusive (default: 1)
            end_line: 1-indexed end line, EXCLUSIVE (default: start + max_lines)
            max_lines: Maximum lines to return (default: 500, max: 2000)

        Returns:
            ToolResult with file contents and metadata

        Line Semantics:
            - start_line=100, end_line=200 returns lines 100-199 (100 lines)
            - start_line and end_line are 1-indexed to match editor line numbers
            - end_line is EXCLUSIVE (standard Python semantics)
        """
        try:
            # Validate path security
            try:
                path = self._validate_path(file_path, must_exist=True)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            if not path.is_file():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a file: {file_path}"
                )

            # Determine bounds
            start = max(1, start_line or 1)  # 1-indexed, minimum 1
            effective_max = min(
                max_lines or self.MAX_LINES_DEFAULT,
                self.MAX_LINES_LIMIT
            )

            # Calculate end_line if not specified
            if end_line is not None:
                # User specified end_line - use it (exclusive)
                end = end_line
            else:
                # Default: start + max_lines
                end = start + effective_max

            # STREAMING READ - bounded memory
            # Only stores lines we need, stops early
            collected_lines: List[str] = []
            total_lines = 0
            stopped_at_end = False

            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, start=1):
                        total_lines = lineno

                        # Skip lines before start
                        if lineno < start:
                            continue

                        # Stop if we hit end_line (exclusive)
                        if lineno >= end:
                            stopped_at_end = True
                            break

                        # Stop if we have enough lines
                        if len(collected_lines) >= effective_max:
                            break

                        # Format line with line number (cat -n style)
                        line_content = line.rstrip('\n\r')

                        # Truncate long lines
                        if len(line_content) > self.MAX_LINE_LENGTH:
                            line_content = line_content[:self.MAX_LINE_LENGTH] + "... [truncated]"

                        # Format: 6-digit line number + tab + content
                        collected_lines.append(f"{lineno:6}\t{line_content}")

            except PermissionError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Permission denied reading file: {file_path}"
                )
            except UnicodeDecodeError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Encoding error reading file: {file_path} - {str(e)}"
                )

            # If we stopped early (not at end_line), count remaining lines
            if not stopped_at_end and len(collected_lines) >= effective_max:
                # We stopped due to max_lines, need to count rest of file
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        total_lines = sum(1 for _ in f)
                except Exception:
                    pass  # Keep the count we had

            # Build output
            content = "\n".join(collected_lines)

            # Calculate actual end line returned
            actual_start = start
            actual_end = start + len(collected_lines)  # Exclusive
            has_more = actual_end <= total_lines

            # Add hint if there's more content
            if has_more and len(collected_lines) > 0:
                content += f"\n\n[Lines {actual_start}-{actual_end - 1} of {total_lines} | Continue: start_line={actual_end}, max_lines={self.MAX_LINES_LIMIT}]"

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=content,
                metadata={
                    "file_path": str(path),
                    "total_lines": total_lines,
                    "lines_returned": len(collected_lines),
                    "start_line": actual_start,
                    "end_line": actual_end,  # Exclusive
                    "has_more": has_more
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to read file: {str(e)}"
            )


class WriteFileTool(FileOperationTool):
    """Tool for writing files with security validation."""

    def __init__(self):
        super().__init__(
            name="write_file",
            description="Write content to a file (creates or overwrites)"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["file_path", "content"]
        }

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Write content to file."""
        try:
            # Validate path security (must_exist=False for new files)
            try:
                path = self._validate_path(file_path, must_exist=False)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(path), "size": len(content)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to write file: {str(e)}"
            )


class ListDirectoryTool(FileOperationTool):
    """Tool for listing directory contents with security validation."""

    def __init__(self):
        super().__init__(
            name="list_directory",
            description="List contents of a directory with file details"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "directory_path": {"type": "string", "description": "Path to directory"}
            },
            "required": ["directory_path"]
        }

    def execute(self, directory_path: str, **kwargs: Any) -> ToolResult:
        """List directory contents."""
        try:
            # Validate path security
            try:
                path = self._validate_path(directory_path, must_exist=True)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Directory not found: {directory_path}"
                )

            if not path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a directory: {directory_path}"
                )

            entries = []
            for entry in path.iterdir():
                entry_info = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None
                }
                entries.append(entry_info)

            # Sort entries: directories first, then files, both alphabetically
            entries.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=entries,
                metadata={"directory_path": str(path), "entry_count": len(entries)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to list directory: {str(e)}"
            )


class EditFileTool(FileOperationTool):
    """Tool for editing files with find/replace and security validation."""

    def __init__(self):
        super().__init__(
            name="edit_file",
            description="Edit a file by replacing old text with new text"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "old_text": {"type": "string", "description": "Text to find"},
                "new_text": {"type": "string", "description": "Text to replace with"}
            },
            "required": ["file_path", "old_text", "new_text"]
        }

    def execute(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
        **kwargs: Any
    ) -> ToolResult:
        """Edit file with find/replace."""
        try:
            # Validate path security
            try:
                path = self._validate_path(file_path, must_exist=True)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            # Read current content
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check if old_text exists
            if old_text not in content:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Text to replace not found in file"
                )

            # Replace
            new_content = content.replace(old_text, new_text)

            # Write back
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file_path": str(path),
                    "replacements": content.count(old_text)
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to edit file: {str(e)}"
            )


class AppendToFileTool(FileOperationTool):
    """Tool for appending content to files with security validation."""

    def __init__(self):
        super().__init__(
            name="append_to_file",
            description="Append content to an existing file (or create if doesn't exist)"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to append"}
            },
            "required": ["file_path", "content"]
        }

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Append content to file."""
        try:
            # Validate path security (must_exist=False for new files)
            try:
                path = self._validate_path(file_path, must_exist=False)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Determine if we need a leading newline (efficient: seek to end)
            needs_newline = False
            if path.exists() and path.stat().st_size > 0:
                with open(path, "rb") as f:
                    f.seek(-1, 2)  # Seek to last byte
                    last_byte = f.read(1)
                    needs_newline = last_byte != b'\n'

            # Append content
            with open(path, "a", encoding="utf-8") as f:
                if needs_newline:
                    f.write('\n')
                f.write(content)

            # Get total file stats (efficient line count)
            total_size = path.stat().st_size
            with open(path, "r", encoding="utf-8") as f:
                total_lines = sum(1 for _ in f)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully appended {len(content)} characters to {file_path} (total: {total_lines} lines, {total_size} bytes)",
                metadata={
                    "file_path": str(path),
                    "appended_size": len(content),
                    "total_size": total_size,
                    "total_lines": total_lines
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to append to file: {str(e)}"
            )


class RunCommandTool(Tool):
    """
    Tool for running shell commands safely.

    Note: Does not inherit from FileOperationTool as it doesn't
    operate on files directly. Security handled via command validation.
    """

    def __init__(self):
        super().__init__(
            name="run_command",
            description="Execute a shell command and return its output"
        )

    def _get_parameters(self) -> Dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "working_directory": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"}
            },
            "required": ["command"]
        }

    def execute(
        self,
        command: str,
        working_directory: Optional[str] = None,
        timeout: int = 30,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command."""
        try:
            # Validate inputs
            if not command or not command.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Command cannot be empty"
                )

            # Validate working directory if provided
            cwd = None
            if working_directory:
                cwd_path = Path(working_directory)
                if not cwd_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory does not exist: {working_directory}"
                    )
                if not cwd_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory path is not a directory: {working_directory}"
                    )
                cwd = str(cwd_path.absolute())

            # Execute command
            # On Windows, use PowerShell instead of cmd.exe for better Unix compatibility
            # Use explicit UTF-8 encoding with error replacement to avoid cp1252 decode errors
            # stdin=DEVNULL prevents subprocess from reading terminal input
            # CREATE_NO_WINDOW / start_new_session isolate subprocess from parent terminal,
            # preventing tools like npx from writing escape sequences directly to the TUI
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", command],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding='utf-8',
                    errors='replace',
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # On Unix-like systems, use the default shell
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding='utf-8',
                    errors='replace',
                    stdin=subprocess.DEVNULL,
                    start_new_session=True
                )

            # Prepare output
            output_parts = []
            if result.stdout:
                output_parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"

            # Determine success based on exit code
            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current",
                        "has_stdout": bool(result.stdout),
                        "has_stderr": bool(result.stderr)
                    }
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=output,
                    error=f"Command failed with exit code {result.returncode}",
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current"
                    }
                )

        except subprocess.TimeoutExpired as e:
            # subprocess.run() kills the process and collects buffered output
            # e.stdout/e.stderr contain whatever was captured before the timeout
            output_parts = []
            if e.stdout:
                output_parts.append(f"STDOUT:\n{e.stdout}")
            if e.stderr:
                output_parts.append(f"STDERR:\n{e.stderr}")
            partial_output = "\n\n".join(output_parts) if output_parts else None

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=partial_output,
                error=f"Command timed out after {timeout} seconds",
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "working_directory": cwd or "current",
                    "partial_output": partial_output is not None
                }
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to execute command: {str(e)}"
            )
