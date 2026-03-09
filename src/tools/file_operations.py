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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.observability import get_logger
from src.tools.command_safety import check_command_safety, clamp_timeout

from .base import Tool, ToolResult, ToolStatus
from .search_tools import validate_path_security

logger = get_logger("tools.file_operations")


class FileOperationTool(Tool):
    """
    Base class for file operation tools with shared security validation.

    Provides:
    - Path validation with traversal protection
    - Configurable workspace root for testing
    """

    # Class-level workspace root override (for testing)
    # Set this to allow operations in test directories
    _workspace_root: Path | None = None

    def _validate_path(
        self, file_path: str, must_exist: bool = True, allow_outside_workspace: bool = False
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
            allow_files_outside_workspace=allow_outside_workspace,
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
    MAX_LINES_DEFAULT = 1000  # Balanced default - read meaningful chunks
    MAX_LINES_LIMIT = 2000  # Hard cap per request
    MAX_LINE_LENGTH = 2000  # Truncate lines longer than this

    def __init__(self):
        super().__init__(
            name="read_file", description="Read contents of a file with optional line range support"
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema (canonical source is tool_schemas.py)."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line (exclusive)"},
                "max_lines": {"type": "integer", "description": "Max lines to return"},
            },
            "required": ["file_path"],
        }

    def execute(
        self,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        max_lines: int | None = None,
        **kwargs: Any,
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
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}",
                )

            if not path.is_file():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a file: {file_path}",
                )

            # Determine bounds
            start = max(1, start_line or 1)  # 1-indexed, minimum 1
            effective_max = min(max_lines or self.MAX_LINES_DEFAULT, self.MAX_LINES_LIMIT)

            # Calculate end_line if not specified
            if end_line is not None:
                # User specified end_line - use it (exclusive)
                end = end_line
            else:
                # Default: start + max_lines
                end = start + effective_max

            # STREAMING READ - bounded memory
            # Only stores lines we need, stops early
            collected_lines: list[str] = []
            total_lines = 0
            stopped_at_end = False

            try:
                with open(path, encoding="utf-8", errors="replace") as f:
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
                        line_content = line.rstrip("\n\r")

                        # Truncate long lines
                        if len(line_content) > self.MAX_LINE_LENGTH:
                            line_content = line_content[: self.MAX_LINE_LENGTH] + "... [truncated]"

                        # Format: 6-digit line number + tab + content
                        collected_lines.append(f"{lineno:6}\t{line_content}")

            except PermissionError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Permission denied reading file: {file_path}",
                )
            except UnicodeDecodeError as e:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Encoding error reading file: {file_path} - {str(e)}",
                )

            # If we stopped early (not at end_line), count remaining lines
            if not stopped_at_end and len(collected_lines) >= effective_max:
                # We stopped due to max_lines, need to count rest of file
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
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
                    "has_more": has_more,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to read file: {str(e)}",
            )


class WriteFileTool(FileOperationTool):
    """Tool for writing files with security validation."""

    def __init__(self):
        super().__init__(
            name="write_file", description="Write content to a file (creates or overwrites)"
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["file_path", "content"],
        }

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Write content to file."""
        try:
            # Validate path security (must_exist=False for new files)
            try:
                path = self._validate_path(file_path, must_exist=False)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(path), "size": len(content)},
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to write file: {str(e)}",
            )


class ListDirectoryTool(FileOperationTool):
    """Tool for listing directory contents with security validation."""

    def __init__(self):
        super().__init__(
            name="list_directory", description="list contents of a directory with file details"
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "directory_path": {"type": "string", "description": "Path to directory"}
            },
            "required": ["directory_path"],
        }

    def execute(self, directory_path: str, **kwargs: Any) -> ToolResult:
        """list directory contents."""
        try:
            # Validate path security
            try:
                path = self._validate_path(directory_path, must_exist=True)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Directory not found: {directory_path}",
                )

            if not path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a directory: {directory_path}",
                )

            entries = []
            for entry in path.iterdir():
                stat = entry.stat()
                mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                entry_info = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                    "mtime": mtime_iso,
                }
                entries.append(entry_info)

            # Sort entries: directories first, then files, both alphabetically
            entries.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))

            # Format as human-readable text so str() in downstream
            # consumers (agent, subagent, VS Code serializer) is a no-op
            output_lines = []
            for e in entries:
                if e["type"] == "directory":
                    output_lines.append(f"[dir]  {e['name']}/")
                else:
                    size_str = f" ({e['size']} bytes)" if e["size"] is not None else ""
                    output_lines.append(f"[file] {e['name']}{size_str}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(output_lines),
                metadata={
                    "directory_path": str(path),
                    "entry_count": len(entries),
                    "entries": entries,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to list directory: {str(e)}",
            )


class EditFileTool(FileOperationTool):
    """Tool for editing files with find/replace and security validation."""

    def __init__(self):
        super().__init__(
            name="edit_file", description="Edit a file by replacing old text with new text"
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "old_text": {"type": "string", "description": "Text to find"},
                "new_text": {"type": "string", "description": "Text to replace with"},
            },
            "required": ["file_path", "old_text", "new_text"],
        }

    def execute(self, file_path: str, old_text: str, new_text: str, **kwargs: Any) -> ToolResult:
        """Edit file with find/replace."""
        try:
            # Validate path security
            try:
                path = self._validate_path(file_path, must_exist=True)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )
            except FileNotFoundError:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}",
                )

            # Read current content
            with open(path, encoding="utf-8") as f:
                content = f.read()

            # Check if old_text exists
            if old_text not in content:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Text to replace not found in file",
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
                metadata={"file_path": str(path), "replacements": content.count(old_text)},
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to edit file: {str(e)}",
            )


class AppendToFileTool(FileOperationTool):
    """Tool for appending content to files with security validation."""

    def __init__(self):
        super().__init__(
            name="append_to_file",
            description="Append content to an existing file (or create if doesn't exist)",
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["file_path", "content"],
        }

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Append content to file."""
        try:
            # Validate path security (must_exist=False for new files)
            try:
                path = self._validate_path(file_path, must_exist=False)
            except ValueError as e:
                return ToolResult(
                    tool_name=self.name, status=ToolStatus.ERROR, output=None, error=str(e)
                )

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Determine if we need a leading newline (efficient: seek to end)
            needs_newline = False
            if path.exists() and path.stat().st_size > 0:
                with open(path, "rb") as f:
                    f.seek(-1, 2)  # Seek to last byte
                    last_byte = f.read(1)
                    needs_newline = last_byte != b"\n"

            # Append content
            with open(path, "a", encoding="utf-8") as f:
                if needs_newline:
                    f.write("\n")
                f.write(content)

            # Get total file stats (efficient line count)
            total_size = path.stat().st_size
            with open(path, encoding="utf-8") as f:
                total_lines = sum(1 for _ in f)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully appended {len(content)} characters to {file_path} (total: {total_lines} lines, {total_size} bytes)",
                metadata={
                    "file_path": str(path),
                    "appended_size": len(content),
                    "total_size": total_size,
                    "total_lines": total_lines,
                },
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to append to file: {str(e)}",
            )


class RunCommandTool(Tool):
    """
    Tool for running shell commands safely.

    Supports both synchronous (foreground) and asynchronous (background) execution.
    When background=True, delegates to BackgroundTaskRegistry for non-blocking execution.

    Note: Does not inherit from FileOperationTool as it doesn't
    operate on files directly. Security handled via command validation.
    """

    def __init__(self, registry=None):
        super().__init__(
            name="run_command", description="Execute a shell command and return its output"
        )
        self._registry = registry

    def _get_parameters(self) -> dict[str, Any]:
        """Get parameter schema."""
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "working_directory": {"type": "string", "description": "Working directory"},
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Timeout in seconds (default: 120). Use higher values for "
                        "long-running commands like test suites or builds (max: 600)"
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Run in background (non-blocking). Returns immediately with a task ID. "
                        "You will be automatically notified when the task completes. "
                        "Use for long-running operations like test suites, builds, or linters."
                    ),
                },
            },
            "required": ["command"],
        }

    async def execute_async(
        self,
        command: str,
        working_directory: str | None = None,
        timeout: int = 120,
        background: bool = False,
        description: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Async execution path -- required for background=True (registry.launch is async)."""
        if not background:
            # Foreground: delegate to sync execute() (will be run in thread pool by ToolExecutor)
            return self.execute(
                command=command,
                working_directory=working_directory,
                timeout=timeout,
                **kwargs,
            )

        # --- Background path ---
        if self._registry is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Background execution not available (no task registry configured)",
            )

        if not command or not command.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Command cannot be empty",
            )

        # Validate working directory (same checks as sync path)
        work_dir = None
        if working_directory:
            cwd_path = Path(working_directory)
            if not cwd_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory does not exist: {working_directory}",
                )
            if not cwd_path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Working directory path is not a directory: {working_directory}",
                )
            work_dir = str(cwd_path.absolute())

        task_id, error = await self._registry.launch(
            command=command,
            description=description,
            working_dir=work_dir,
            timeout=timeout if timeout != 120 else None,  # let registry use its default
        )

        if error:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=error,
            )

        active = self._registry.active_count()
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=(
                f"Background task launched: {task_id}\n"
                f"Command: {command}\n"
                f"Active background tasks: {active}\n"
                "You will be notified when it completes."
            ),
        )

    def execute(
        self, command: str, working_directory: str | None = None, timeout: int = 120, **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command."""
        try:
            # Validate inputs
            if not command or not command.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Command cannot be empty",
                )

            # --- COMMAND SAFETY CHECK ---
            is_safe, safety_reason = check_command_safety(command)
            if not is_safe:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=(
                        f"[BLOCKED] Command rejected by safety controls: {safety_reason}\n"
                        "This command matches a pattern that could cause irreversible damage "
                        "or data exfiltration. If this command is legitimately needed, the user "
                        "must run it manually in their terminal."
                    ),
                )

            # --- CLAMP TIMEOUT ---
            timeout = clamp_timeout(timeout)

            # Validate working directory if provided
            cwd = None
            if working_directory:
                cwd_path = Path(working_directory)
                if not cwd_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory does not exist: {working_directory}",
                    )
                if not cwd_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory path is not a directory: {working_directory}",
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
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
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
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )

            # Prepare output
            output_parts = []
            if result.stdout:
                output_parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"

            # Audit log the execution
            logger.info(
                f"[COMMAND_AUDIT] Executed: {command[:200]}, exit_code={result.returncode}, timeout={timeout}s"
            )

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
                        "has_stderr": bool(result.stderr),
                    },
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
                        "working_directory": cwd or "current",
                    },
                )

        except subprocess.TimeoutExpired as e:
            # subprocess.run() kills the process and collects buffered output.
            # e.stdout/e.stderr may be str (text=True) or bytes (on some platforms),
            # or None/empty if PowerShell hadn't flushed its buffers before kill.
            output_parts = []
            stdout = e.stdout
            stderr = e.stderr
            # Handle bytes (can happen on some platforms despite text=True)
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr}")
            partial_output = (
                "\n\n".join(output_parts)
                if output_parts
                else ("(no output captured - process was killed before producing output)")
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=partial_output,
                error=f"Command timed out after {timeout} seconds. "
                f"Use a longer timeout if the command needs more time (max 600s).",
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "working_directory": cwd or "current",
                    "partial_output": bool(output_parts),
                },
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to execute command: {str(e)}",
            )
